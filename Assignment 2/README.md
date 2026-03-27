# Memory Allocation and Management Simulator

## Overview
This project is a simulation of contiguous memory allocation in operating systems. It models how an operating system dynamically allocates and deallocates memory for processes while managing fragmentation. The simulator uses a linked list data structure to represent memory and applies four classical allocation strategies to assign memory to processes.

The system processes a sequence of allocation and deallocation requests and logs the memory state after each operation. This allows observation of how memory evolves over time and how fragmentation occurs under different algorithms.

## Objectives
The objective of this project is to implement a memory manager that simulates contiguous allocation, supports multiple allocation strategies, manages memory using a linked list, correctly splits and merges memory blocks, and demonstrates fragmentation behavior under different algorithms.

## Features
- Fixed memory size (256 MB)
- Linked list-based memory representation
- Dynamic allocation and deallocation of processes
- First Fit, Next Fit, Best Fit, and Worst Fit algorithms
- Automatic splitting of holes during allocation
- Automatic merging of adjacent holes during deallocation
- Detailed logging after every operation
- Fragmentation statistics including number of holes, total free memory, and largest hole
- Same workload executed for all algorithms for comparison

## Memory Representation
Memory is represented as a singly linked list where each node corresponds to a contiguous memory block. Each block contains a start address, size in MB, status (free or allocated), and process ID if allocated.

Initial memory state:
[Hole: 256 MB (0-255)]

Example after allocation:
[Process A: 40 MB (0-39)] -> [Hole: 216 MB (40-255)]

## Allocation Algorithms
First Fit scans memory from the beginning and selects the first hole large enough.  
Next Fit continues searching from the last allocation point.  
Best Fit searches the entire memory and selects the smallest suitable hole.  
Worst Fit searches the entire memory and selects the largest available hole.

## Program Workflow
1. Initialize memory as one large hole
2. Process workload operations one by one
3. For allocation:
   - Find suitable hole using selected algorithm
   - Split hole if needed
4. For deallocation:
   - Mark process as free
   - Merge adjacent holes
5. Log memory state after each operation

## Input Format
Allocation:
("A", process_id, size)

Deallocation:
("D", process_id)

## Example Workload
("A", "A", 40)  
("A", "B", 25)  
("A", "C", 60)  
("D", "B")  
("A", "D", 20)  
("A", "E", 35)  
("D", "A")  
("A", "F", 15)  
("D", "C")  

## How to Run
Requirements: Python 3.x  

Steps:
1. Save file as memory_manager.py  
2. Open terminal  
3. Run command:  
python memory_manager.py  

## Example Output
ALGORITHM: FIRST FIT

Operation: Allocate 40 MB for Process A -> SUCCESS  
Memory State: [Process A: 40 MB (0-39)] -> [Hole: 216 MB (40-255)]  
Holes: 1 | Total Free Memory: 216 MB | Largest Hole: 216 MB  

Operation: Allocate 25 MB for Process B -> SUCCESS  
Memory State: [Process A: 40 MB (0-39)] -> [Process B: 25 MB (40-64)] -> [Hole: 191 MB (65-255)]  
Holes: 1 | Total Free Memory: 191 MB | Largest Hole: 191 MB  

Operation: Process B terminates -> SUCCESS  
Memory State: [Process A: 40 MB (0-39)] -> [Hole: 216 MB (40-255)]  
Holes: 1 | Total Free Memory: 216 MB | Largest Hole: 216 MB  

Allocation failure example:
Operation: Allocate 300 MB for Process X -> FAILED (no suitable hole found)  

## Output Explanation
Each log includes the operation performed, whether it succeeded or failed, the memory state in order, and fragmentation statistics. This helps visualize how memory changes step by step.

## Design Details
The simulator uses a singly linked list because it naturally represents contiguous memory. Each node represents a memory block. Allocation traverses the list and splits holes if needed. Deallocation marks blocks as free and merges adjacent holes. Next Fit uses a pointer to remember the last allocation position.

## Fragmentation Analysis
The simulator demonstrates external fragmentation. Memory becomes divided into smaller holes over time. Some allocation requests may fail even if total free memory is sufficient. Different algorithms produce different fragmentation patterns.

## Error Handling
- Allocation fails if no suitable hole exists
- Deallocation fails if process is not found
- Exact-fit allocations do not create extra holes
- Adjacent holes are always merged

## Conclusion
This project demonstrates how memory allocation strategies affect memory efficiency and fragmentation. It provides practical insight into how operating systems manage memory dynamically.
