#include <stdio.h>
#include <stdlib.h>
#include <pthread.h>
#include <unistd.h>
#include <string.h>
#include <time.h>

#define NUM_REPLICAS 3
#define TOTAL_READERS 18
#define WRITER_ITERATIONS 6
#define MAX_CONTENT_LEN 256

const char *replica_files[NUM_REPLICAS] = {
    "replica1.txt",
    "replica2.txt",
    "replica3.txt"
};

pthread_mutex_t state_mutex = PTHREAD_MUTEX_INITIALIZER;
pthread_mutex_t log_mutex = PTHREAD_MUTEX_INITIALIZER;

pthread_cond_t can_read = PTHREAD_COND_INITIALIZER;
pthread_cond_t can_write = PTHREAD_COND_INITIALIZER;

/* Shared state */
int active_readers = 0;
int waiting_readers = 0;
int waiting_writers = 0;
int writer_active = 0;

/* Load-balancing state: how many readers are currently reading each replica */
int readers_on_replica[NUM_REPLICAS] = {0, 0, 0};

/* Writer version/content tracking */
int current_version = 0;
char current_content[MAX_CONTENT_LEN] = "Initial content (version 0)";

/* ----------------------------- Utility Functions ----------------------------- */

int random_between(int min, int max) {
    return min + rand() % (max - min + 1);
}

void initialize_replicas() {
    FILE *fp;
    for (int i = 0; i < NUM_REPLICAS; i++) {
        fp = fopen(replica_files[i], "w");
        if (fp == NULL) {
            perror("Error creating replica file");
            exit(1);
        }
        fprintf(fp, "%s\n", current_content);
        fclose(fp);
    }

    fp = fopen("log.txt", "w");
    if (fp == NULL) {
        perror("Error creating log file");
        exit(1);
    }
    fprintf(fp, "=== Readers-Writers Log Started ===\n");
    fclose(fp);
}

void read_file_content(const char *filename, char *buffer, size_t size) {
    FILE *fp = fopen(filename, "r");
    if (fp == NULL) {
        snprintf(buffer, size, "ERROR: could not open file");
        return;
    }

    if (fgets(buffer, (int)size, fp) == NULL) {
        snprintf(buffer, size, "(empty file)");
    } else {
        buffer[strcspn(buffer, "\n")] = '\0';
    }

    fclose(fp);
}

void write_all_replicas(const char *new_content) {
    for (int i = 0; i < NUM_REPLICAS; i++) {
        FILE *fp = fopen(replica_files[i], "w");
        if (fp == NULL) {
            perror("Error writing to replica file");
            exit(1);
        }
        fprintf(fp, "%s\n", new_content);
        fclose(fp);
    }
}

int choose_best_replica() {
    int best = 0;
    for (int i = 1; i < NUM_REPLICAS; i++) {
        if (readers_on_replica[i] < readers_on_replica[best]) {
            best = i;
        }
    }
    return best;
}

void write_log_entry(const char *operation,
                     int thread_id,
                     int replica_index,
                     const char *content_snapshot) {
    pthread_mutex_lock(&log_mutex);

    FILE *logf = fopen("log.txt", "a");
    if (logf == NULL) {
        perror("Error opening log file");
        pthread_mutex_unlock(&log_mutex);
        return;
    }

    /* Take consistent snapshot of state for logging */
    pthread_mutex_lock(&state_mutex);
    int r0 = readers_on_replica[0];
    int r1 = readers_on_replica[1];
    int r2 = readers_on_replica[2];
    int w_active = writer_active;
    pthread_mutex_unlock(&state_mutex);

    fprintf(logf, "--------------------------------------------------\n");
    fprintf(logf, "Operation: %s\n", operation);

    if (strcmp(operation, "READ") == 0) {
        fprintf(logf, "Reader ID: %d\n", thread_id);
        fprintf(logf, "Replica Accessed: %s\n", replica_files[replica_index]);
    } else {
        fprintf(logf, "Writer ID: %d\n", thread_id);
        fprintf(logf, "Replica Accessed: ALL REPLICAS\n");
    }

    fprintf(logf, "Readers per replica: [%d, %d, %d]\n", r0, r1, r2);
    fprintf(logf, "Writer active: %s\n", w_active ? "YES" : "NO");
    fprintf(logf, "Current content: %s\n", content_snapshot);
    fclose(logf);

    pthread_mutex_unlock(&log_mutex);
}

/* ----------------------------- Thread Functions ----------------------------- */

void *reader_thread(void *arg) {
    int reader_id = *((int *)arg);
    free(arg);

    /* Random delay before trying to access */
    usleep(random_between(100000, 700000));

    pthread_mutex_lock(&state_mutex);
    waiting_readers++;

    /* Writer priority:
       If a writer is active OR at least one writer is waiting,
       this reader must wait. */
    while (writer_active || waiting_writers > 0) {
        pthread_cond_wait(&can_read, &state_mutex);
    }

    waiting_readers--;

    int chosen_replica = choose_best_replica();
    active_readers++;
    readers_on_replica[chosen_replica]++;

    pthread_mutex_unlock(&state_mutex);

    /* Simulate reading */
    char buffer[MAX_CONTENT_LEN];
    read_file_content(replica_files[chosen_replica], buffer, sizeof(buffer));
    usleep(random_between(150000, 500000));

    write_log_entry("READ", reader_id, chosen_replica, buffer);

    pthread_mutex_lock(&state_mutex);

    active_readers--;
    readers_on_replica[chosen_replica]--;

    /* If this was the last active reader and a writer is waiting,
       wake one writer. */
    if (active_readers == 0 && waiting_writers > 0) {
        pthread_cond_signal(&can_write);
    }

    pthread_mutex_unlock(&state_mutex);

    return NULL;
}

void *writer_thread(void *arg) {
    int writer_id = *((int *)arg);

    for (int i = 0; i < WRITER_ITERATIONS; i++) {
        sleep(random_between(1, 3));

        pthread_mutex_lock(&state_mutex);
        waiting_writers++;

        /* Writer can proceed only when:
           - no writer is active
           - no readers are active */
        while (writer_active || active_readers > 0) {
            pthread_cond_wait(&can_write, &state_mutex);
        }

        waiting_writers--;
        writer_active = 1;

        pthread_mutex_unlock(&state_mutex);

        /* Critical writing phase */
        char new_content[MAX_CONTENT_LEN];
        current_version++;
        snprintf(new_content, sizeof(new_content),
                 "Updated by writer | version %d", current_version);

        write_all_replicas(new_content);

        /* Update shared content snapshot */
        pthread_mutex_lock(&state_mutex);
        strncpy(current_content, new_content, sizeof(current_content) - 1);
        current_content[sizeof(current_content) - 1] = '\0';
        pthread_mutex_unlock(&state_mutex);

        usleep(random_between(200000, 500000));

        write_log_entry("WRITE", writer_id, -1, new_content);

        pthread_mutex_lock(&state_mutex);
        writer_active = 0;

        /* Writer priority:
           if more writers are waiting, wake next writer first.
           otherwise let all waiting readers compete. */
        if (waiting_writers > 0) {
            pthread_cond_signal(&can_write);
        } else {
            pthread_cond_broadcast(&can_read);
        }

        pthread_mutex_unlock(&state_mutex);
    }

    return NULL;
}

/* ---------------------------------- Main ----------------------------------- */

int main() {
    srand((unsigned int)time(NULL));

    initialize_replicas();

    pthread_t writer;
    pthread_t readers[TOTAL_READERS];

    int writer_id = 1;

    if (pthread_create(&writer, NULL, writer_thread, &writer_id) != 0) {
        perror("Failed to create writer thread");
        return 1;
    }

    for (int i = 0; i < TOTAL_READERS; i++) {
        int *reader_id = malloc(sizeof(int));
        if (reader_id == NULL) {
            perror("Memory allocation failed");
            return 1;
        }
        *reader_id = i + 1;

        if (pthread_create(&readers[i], NULL, reader_thread, reader_id) != 0) {
            perror("Failed to create reader thread");
            free(reader_id);
            return 1;
        }

        /* Random spawn interval for readers */
        usleep(random_between(80000, 300000));
    }

    for (int i = 0; i < TOTAL_READERS; i++) {
        pthread_join(readers[i], NULL);
    }

    pthread_join(writer, NULL);

    printf("Program completed successfully.\n");
    printf("Check replica1.txt, replica2.txt, replica3.txt and log.txt\n");

    pthread_mutex_destroy(&state_mutex);
    pthread_mutex_destroy(&log_mutex);
    pthread_cond_destroy(&can_read);
    pthread_cond_destroy(&can_write);

    return 0;
}
