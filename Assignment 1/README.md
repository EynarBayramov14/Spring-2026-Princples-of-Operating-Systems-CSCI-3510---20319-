# Readers–Writers Problem with Load Balancing (Writer Priority)

## Principles of Operating Systems – Assignment 1

## Overview

This project implements a modified version of the classical **Readers–Writers synchronization problem** using **C and POSIX threads (pthreads)**. The system simulates multiple reader threads accessing replicated files and a single writer thread that periodically updates those files.

Unlike the traditional readers–writers problem, this assignment introduces two additional requirements:

1. **Writer Priority**  
   If a writer intends to access the file, all new readers must wait until the writer completes its operation.

2. **Load Balancing for Readers**  
   There are three replicas of the same file, and reader threads must be distributed across these replicas to balance the load.

The program ensures thread-safe access to shared resources while maintaining efficiency and fairness between readers and the writer.

---

# System Description

The system contains:

- **Multiple reader threads**
- **One writer thread**
- **Three replicas of the same text file**
- **A log file for tracking all operations**

Reader threads spawn at **random intervals**, read one of the file replicas **once**, and terminate.

The writer thread runs in a **loop**, sleeps for a random duration, then updates **all three replicas simultaneously** while blocking readers.

After each read or write operation, the system records a detailed entry in a **log file**.

---

# Program Features

The implementation provides the following features:

- Multiple concurrent **reader threads**
- One continuously running **writer thread**
- **Writer priority synchronization**
- **Balanced reader distribution across file replicas**
- **Thread-safe logging**
- **Random thread spawning to simulate real concurrency**
- **Protection against race conditions**

The system demonstrates fundamental **Operating System synchronization concepts** such as mutexes, condition variables, and critical sections.

---

# File Structure

The project directory contains the following files:
rw_load_balancer.c → main source code
replica1.txt → first file replica
replica2.txt → second file replica
replica3.txt → third file replica
log.txt → log file generated during execution
README.md → project documentation

The program automatically initializes the replica files and updates them during execution.

---

# Synchronization Design

To ensure correct synchronization between threads, the program uses the following primitives from the **POSIX pthread library**:

## Mutex

A mutex named `state_mutex` protects shared variables such as:

- number of active readers
- number of waiting readers
- number of waiting writers
- writer activity status
- number of readers accessing each replica

This mutex guarantees that updates to shared variables occur safely without race conditions.

Another mutex named `log_mutex` ensures that multiple threads do not write to the log file at the same time.

---

## Condition Variables

Two condition variables are used to coordinate thread execution:

### can_read

Reader threads wait on this condition when:

- the writer is currently active
- a writer is waiting to access the file

This ensures **writer priority**.

### can_write

The writer waits on this condition until:

- no readers are currently active
- no other writer is active

Once the condition is satisfied, the writer can safely update the replicas.

---

# Writer Priority Implementation

Writer priority is enforced by preventing readers from entering the critical section when a writer is waiting.

Reader threads execute the following condition before accessing a file:
while(writer_active || waiting_writers > 0)

This means that:

- if a writer is currently writing, readers must wait
- if a writer is waiting to write, new readers must also wait

This approach prevents **writer starvation**, which can occur in the classical readers–writers problem.

After the writer finishes, it wakes either:

- the next waiting writer, or
- all waiting readers if no writers remain

---

# Load Balancing Strategy

To balance reader access across the three file replicas, the system maintains an array:
readers_on_replica[3]

This array stores the number of readers currently accessing each replica.

When a new reader is allowed to proceed, it selects the replica with the **lowest number of active readers**.

Example:

| Replica | Current Readers |
|--------|----------------|
| replica1 | 2 |
| replica2 | 0 |
| replica3 | 1 |

The next reader will select **replica2** because it has the smallest load.

This strategy minimizes the difference between reader counts and distributes work evenly.

---

# Thread Behavior

## Reader Threads

Each reader thread performs the following steps:

1. Sleep for a random short duration
2. Request permission to read
3. Wait if a writer is active or waiting
4. Select the least loaded replica
5. Read the file once
6. Write a log entry
7. Release access
8. Terminate

Each reader reads **only once**, which simulates independent file access requests.

---

## Writer Thread

The writer thread runs in a loop and performs these steps:

1. Sleep for a random duration
2. Announce its intention to write
3. Wait until no readers are active
4. Lock access to all replicas
5. Update the content of all three files
6. Write a log entry
7. Release access to readers
8. Repeat the process

During the writing phase, **no readers are allowed to access any file replica**.

---

# Logging System

Every read and write operation generates a detailed entry in `log.txt`.

Each log entry contains:

- operation type (READ or WRITE)
- reader or writer ID
- accessed replica
- number of readers on each replica
- whether the writer is active
- current file content

Example log entry:
Operation: READ
Reader ID: 5
Replica Accessed: replica2.txt
Readers per replica: [1,2,0]
Writer active: NO
Current content: Updated by writer | version 2


Example write entry:
Operation: WRITE
Writer ID: 1
Replica Accessed: ALL REPLICAS
Readers per replica: [0,0,0]
Writer active: YES
Current content: Updated by writer | version 3

The log file helps verify synchronization correctness and system behavior.

---

# Compilation

To compile the program, use the following command:
gcc rw_load_balancer.c -o rw_load_balancer -lpthread

This command compiles the program and links the POSIX thread library.

---

# Running the Program

After compilation, run the program using:
./rw_load_balancer

When execution completes, the terminal will display:
Program completed successfully.
Check replica1.txt, replica2.txt, replica3.txt and log.txt

You can then open `log.txt` to observe all read and write operations.

---

# Expected Behavior

During execution:

- readers will access replicas concurrently
- readers will be distributed across the three replicas
- the writer will periodically block readers
- the writer will update all replicas consistently
- logs will record every operation

Because thread scheduling is non-deterministic, the exact order of operations may vary in each run.

---

# Correctness and Safety

The implementation guarantees the following:

- no reader and writer access files simultaneously
- the writer updates all replicas during exclusive access
- writer priority is maintained
- readers are distributed evenly across replicas
- logging operations are thread-safe
- shared variables are protected from race conditions

---

# Conclusion

This project demonstrates a complete solution to the Readers–Writers synchronization problem with additional constraints for writer priority and load balancing.

The program uses mutexes and condition variables to ensure correct coordination between threads while maintaining efficiency and fairness. By distributing readers across multiple replicas and prioritizing writer operations, the system satisfies all requirements of the assignment and reflects key synchronization concepts studied in the Principles of Operating Systems course.
