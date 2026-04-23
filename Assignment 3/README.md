# File System Allocation Simulator

**Operating Systems – Assignment 3**

* * *

## 📌 Overview

This project implements a **File System Allocation Simulator** that models how an operating system manages files on disk using different allocation strategies.

The simulator demonstrates how disk blocks are assigned to files, how free space is managed, and how various file operations are handled in a persistent storage system.

### 🎯 Objective

To simulate and compare three fundamental file allocation methods:

-   **Contiguous Allocation**
    
-   **FAT (File Allocation Table) – Linked Allocation**
    
-   **I-node Allocation (with direct + indirect pointers)**
    

* * *

## ⚙️ Features

### 🧱 Disk Simulation

-   Disk is represented as a **linear array of fixed-size blocks**
    
-   Each block is tracked as **free or allocated**
    
-   Supports:
    
    -   Free space tracking
        
    -   External fragmentation measurement
        

* * *

### 📂 File System Operations

The simulator supports the following commands:

| Command | Description |
| --- | --- |
| `MKDIR <path>` | Create a directory |
| `CREATE <path> [size] [data]` | Create a file |
| `DELETE <path>` | Delete a file or directory |
| `OPEN <path>` | Open a file |
| `CLOSE <fd>` | Close a file |
| `READ <fd> <offset> <length>` | Read from file |
| `WRITE <fd> <offset> <data>` | Write to file |
| `LINK <target> <link>` | Create hard link |
| `SYMLINK <target> <link>` | Create soft link |
| `LS [path]` | List directory contents |
| `STAT <path>` | Show file metadata |
| `STATUS` | Show system statistics |
| `JOURNAL` | Show journal log |
| `CRASH_DELETE <path>` | Simulate crash during delete |
| `RECOVER` | Recover from journal |

* * *

## 🧠 Allocation Algorithms

### 1\. Contiguous Allocation

-   Stores file blocks in a **continuous sequence**
    
-   Advantages:
    
    -   Fast sequential access (1 seek)
        
-   Disadvantages:
    
    -   External fragmentation
        
-   Simulator tracks:
    
    -   Free runs
        
    -   Fragmentation ratio
        

* * *

### 2\. FAT (Linked Allocation)

-   Uses an **in-memory table** to link blocks
    
-   Each block points to the next block
    
-   Advantages:
    
    -   No external fragmentation
        
-   Disadvantages:
    
    -   Entire FAT must stay in memory
        
-   Simulator tracks:
    
    -   FAT table size (memory overhead)
        
    -   Block chain traversal cost
        

* * *

### 3\. I-node Allocation

-   Each file has an **i-node** containing:
    
    -   File metadata
        
    -   Direct block pointers
        
    -   One indirect pointer block
        
-   Advantages:
    
    -   Efficient for large files
        
    -   Only loaded into memory when file is open
        
-   Simulator features:
    
    -   Direct + indirect block handling
        
    -   Memory usage tracking for loaded i-nodes
        

* * *

## 📁 Directory System & Links

### 📂 Hierarchical Directories

-   Supports nested directories (tree structure)
    
-   Root directory: `/`
    

### 🔗 Hard Links

-   Multiple directory entries reference the same file (inode)
    
-   File is deleted only when:
    
    -   `link_count == 0`
        

### 🔗 Soft Links (Symbolic Links)

-   Separate file pointing to target path
    
-   If target is deleted:
    
    -   Link becomes **broken**
        

* * *

## 🧾 Journaling System

The simulator implements **basic journaling** similar to real file systems (e.g., NTFS, ext3).

### 🔄 Features

-   Logs operations **before execution**
    
-   Tracks:
    
    -   Remove from directory
        
    -   Release inode
        
    -   Free disk blocks
        
-   Supports:
    
    -   `CRASH_DELETE` → simulate failure
        
    -   `RECOVER` → restore consistency
        

* * *

## 📊 Performance Metrics

The simulator provides:

-   **External Fragmentation (Contiguous)**
    
-   **Memory Overhead (FAT & I-node)**
    
-   **Read Performance Simulation**
    
-   **Free block statistics**
    

* * *

## ▶️ How to Run

### 🛠 Requirements

-   Python 3.x
    

* * *

### 🚀 Run Examples

#### Run demo:

    python fs_simulator_truly_final.py --algo contiguous --demo
    

#### Interactive mode:

    python fs_simulator_truly_final.py --algo fat --interactive
    

#### Run workload file:

    python fs_simulator_truly_final.py --algo inode --workload workload.txt
    

* * *

## 🧪 Demo Workload

The project includes a built-in demo demonstrating:

-   File creation
    
-   Read/write operations
    
-   Hard & soft links
    
-   Deletion behavior
    
-   Journaling
    

* * *

## 🏗 Design Highlights

-   Modular architecture:
    
    -   `Disk` → block management
        
    -   `AllocationStrategy` → pluggable algorithms
        
    -   `FileSystemSimulator` → core logic
        
    -   `Journal` → crash recovery simulation
        
-   Object-oriented design for clarity and extensibility
    
-   Strong error handling and validation
    

* * *

## 📌 Assumptions & Simplifications

-   Disk is simulated in memory
    
-   Only **single indirect pointer** is implemented (no double/triple)
    
-   Journaling focuses on **delete operations**
    
-   File contents stored in memory for simulation
    

* * *

## 📈 Conclusion

This simulator demonstrates how different allocation strategies impact:

-   Performance
    
-   Memory usage
    
-   Fragmentation
    

It provides a clear comparison of trade-offs between **Contiguous**, **FAT**, and **I-node** allocation methods.

* * *
