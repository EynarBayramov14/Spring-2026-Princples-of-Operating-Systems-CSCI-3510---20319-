from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, List, Tuple


@dataclass
class MemoryBlock:
    """
    Represents one segment in contiguous memory.

    Attributes:
        start (int): Starting address of the block.
        size (int): Size of the block in MB.
        is_free (bool): True if the block is a free hole, False if allocated.
        process_id (Optional[str]): Process name/id if allocated, otherwise None.
        next (Optional[MemoryBlock]): Pointer to the next memory block.
    """
    start: int
    size: int
    is_free: bool = True
    process_id: Optional[str] = None
    next: Optional["MemoryBlock"] = None


class MemoryManager:
    """
    Simulates contiguous memory management using a linked list.

    Supported allocation algorithms:
        - first_fit
        - next_fit
        - best_fit
        - worst_fit
    """

    def __init__(self, total_memory: int, algorithm: str) -> None:
        """
        Initialize memory manager with one large free hole.

        Args:
            total_memory (int): Total memory size in MB.
            algorithm (str): Allocation strategy to use.
        """
        valid_algorithms = {"first_fit", "next_fit", "best_fit", "worst_fit"}
        if algorithm not in valid_algorithms:
            raise ValueError(
                f"Invalid algorithm '{algorithm}'. "
                f"Choose one of: {', '.join(valid_algorithms)}"
            )

        self.total_memory = total_memory
        self.algorithm = algorithm
        self.head = MemoryBlock(start=0, size=total_memory, is_free=True)
        self.next_fit_last_position: Optional[MemoryBlock] = self.head
        self.logs: List[str] = []

    # -------------------------------------------------------------------------
    # Public simulation methods
    # -------------------------------------------------------------------------

    def allocate(self, process_id: str, size: int) -> bool:
        """
        Allocate memory for a process using the selected algorithm.

        Args:
            process_id (str): Process identifier.
            size (int): Memory requested in MB.

        Returns:
            bool: True if allocation succeeded, False otherwise.
        """
        if size <= 0:
            self._log(
                f"Operation: Allocate {size} MB for Process {process_id} -> FAILED "
                f"(invalid size)"
            )
            return False

        if self._find_process(process_id) is not None:
            self._log(
                f"Operation: Allocate {size} MB for Process {process_id} -> FAILED "
                f"(process already exists)"
            )
            return False

        chosen_block = self._find_hole(size)

        if chosen_block is None:
            self._log(
                f"Operation: Allocate {size} MB for Process {process_id} -> FAILED "
                f"(no suitable hole found)"
            )
            return False

        self._split_and_allocate(chosen_block, process_id, size)
        self._log(f"Operation: Allocate {size} MB for Process {process_id} -> SUCCESS")
        return True

    def deallocate(self, process_id: str) -> bool:
        """
        Deallocate a process and merge adjacent holes if needed.

        Args:
            process_id (str): Process identifier to remove.

        Returns:
            bool: True if deallocation succeeded, False otherwise.
        """
        prev = None
        current = self.head

        while current is not None:
            if not current.is_free and current.process_id == process_id:
                current.is_free = True
                current.process_id = None

                # Merge with next free blocks first
                self._merge_with_next(current)

                # Merge with previous free block if it exists
                if prev is not None and prev.is_free:
                    prev.size += current.size
                    prev.next = current.next
                    current = prev
                    self._merge_with_next(current)

                # For next fit safety, if pointer becomes invalid logically,
                # move it to a valid current free/allocated block
                if self.next_fit_last_position is None:
                    self.next_fit_last_position = self.head

                self._recalculate_starts()
                self._log(f"Operation: Process {process_id} terminates -> SUCCESS")
                return True

            prev = current
            current = current.next

        self._log(
            f"Operation: Process {process_id} terminates -> FAILED "
            f"(process not found)"
        )
        return False

    def run_workload(self, workload: List[Tuple[str, ...]]) -> None:
        """
        Run a list of workload operations.

        Workload format:
            ("A", process_id, size)  -> allocate
            ("D", process_id)        -> deallocate

        Args:
            workload (List[Tuple[str, ...]]): Operations to simulate.
        """
        for operation in workload:
            if not operation:
                continue

            op_type = operation[0].upper()

            if op_type == "A":
                if len(operation) != 3:
                    self._log(f"Operation: {operation} -> FAILED (invalid allocate format)")
                    continue
                _, process_id, size = operation
                self.allocate(str(process_id), int(size))

            elif op_type == "D":
                if len(operation) != 2:
                    self._log(f"Operation: {operation} -> FAILED (invalid deallocate format)")
                    continue
                _, process_id = operation
                self.deallocate(str(process_id))

            else:
                self._log(f"Operation: {operation} -> FAILED (unknown operation)")

    def print_logs(self) -> None:
        """
        Print all collected logs for this simulation.
        """
        print("=" * 80)
        print(f"ALGORITHM: {self.algorithm.upper().replace('_', ' ')}")
        print("=" * 80)
        for entry in self.logs:
            print(entry)
        print()

    # -------------------------------------------------------------------------
    # Allocation algorithm helpers
    # -------------------------------------------------------------------------

    def _find_hole(self, size: int) -> Optional[MemoryBlock]:
        """
        Dispatch to the correct allocation strategy.
        """
        if self.algorithm == "first_fit":
            return self._first_fit(size)
        if self.algorithm == "next_fit":
            return self._next_fit(size)
        if self.algorithm == "best_fit":
            return self._best_fit(size)
        if self.algorithm == "worst_fit":
            return self._worst_fit(size)
        return None

    def _first_fit(self, size: int) -> Optional[MemoryBlock]:
        """
        Find the first hole that is large enough.
        """
        current = self.head
        while current is not None:
            if current.is_free and current.size >= size:
                return current
            current = current.next
        return None

    def _next_fit(self, size: int) -> Optional[MemoryBlock]:
        """
        Find the next suitable hole starting from the last remembered position.
        Search wraps around to the beginning if needed.
        """
        if self.head is None:
            return None

        start_node = self.next_fit_last_position if self.next_fit_last_position else self.head
        current = start_node

        while True:
            if current.is_free and current.size >= size:
                return current

            current = current.next if current.next is not None else self.head

            if current == start_node:
                break

        return None

    def _best_fit(self, size: int) -> Optional[MemoryBlock]:
        """
        Find the smallest hole that is still large enough.
        """
        best = None
        current = self.head

        while current is not None:
            if current.is_free and current.size >= size:
                if best is None or current.size < best.size:
                    best = current
            current = current.next

        return best

    def _worst_fit(self, size: int) -> Optional[MemoryBlock]:
        """
        Find the largest available hole.
        """
        worst = None
        current = self.head

        while current is not None:
            if current.is_free and current.size >= size:
                if worst is None or current.size > worst.size:
                    worst = current
            current = current.next

        return worst

    # -------------------------------------------------------------------------
    # Core linked list memory operations
    # -------------------------------------------------------------------------

    def _split_and_allocate(self, hole: MemoryBlock, process_id: str, size: int) -> None:
        """
        Allocate memory inside a chosen hole.

        If hole size equals request size:
            convert hole directly into allocated process.
        If hole size is larger:
            split into allocated block + remaining free hole.
        """
        if hole.size == size:
            hole.is_free = False
            hole.process_id = process_id

            if self.algorithm == "next_fit":
                self.next_fit_last_position = hole.next if hole.next is not None else self.head

            return

        remaining_hole = MemoryBlock(
            start=hole.start + size,
            size=hole.size - size,
            is_free=True,
            process_id=None,
            next=hole.next
        )

        hole.size = size
        hole.is_free = False
        hole.process_id = process_id
        hole.next = remaining_hole

        if self.algorithm == "next_fit":
            self.next_fit_last_position = remaining_hole

    def _merge_with_next(self, block: MemoryBlock) -> None:
        """
        Merge the given free block with all immediately adjacent free blocks after it.
        """
        while block.next is not None and block.next.is_free:
            block.size += block.next.size
            block.next = block.next.next

    def _find_process(self, process_id: str) -> Optional[MemoryBlock]:
        """
        Find an allocated process block by its process ID.
        """
        current = self.head
        while current is not None:
            if not current.is_free and current.process_id == process_id:
                return current
            current = current.next
        return None

    def _recalculate_starts(self) -> None:
        """
        Recalculate starting addresses after splits/merges.
        Keeps addresses consistent from low memory to high memory.
        """
        current = self.head
        current_start = 0

        while current is not None:
            current.start = current_start
            current_start += current.size
            current = current.next

    # -------------------------------------------------------------------------
    # Logging and statistics
    # -------------------------------------------------------------------------

    def _memory_state_string(self) -> str:
        """
        Return a readable ordered representation of memory blocks.
        """
        parts = []
        current = self.head

        while current is not None:
            end = current.start + current.size - 1
            if current.is_free:
                parts.append(f"[Hole: {current.size} MB ({current.start}-{end})]")
            else:
                parts.append(
                    f"[Process {current.process_id}: {current.size} MB ({current.start}-{end})]"
                )
            current = current.next

        return " -> ".join(parts)

    def _fragmentation_info(self) -> str:
        """
        Return simple fragmentation statistics.
        """
        holes = 0
        total_free = 0
        largest_hole = 0

        current = self.head
        while current is not None:
            if current.is_free:
                holes += 1
                total_free += current.size
                largest_hole = max(largest_hole, current.size)
            current = current.next

        return (
            f"Holes: {holes} | Total Free Memory: {total_free} MB | "
            f"Largest Hole: {largest_hole} MB"
        )

    def _log(self, operation_message: str) -> None:
        """
        Store a formatted log entry after each operation.
        """
        log_entry = (
            f"{operation_message}\n"
            f"Memory State: {self._memory_state_string()}\n"
            f"{self._fragmentation_info()}\n"
            f"{'-' * 80}"
        )
        self.logs.append(log_entry)


# -----------------------------------------------------------------------------
# Sample workload and simulation runner
# -----------------------------------------------------------------------------

def run_all_algorithms(total_memory: int, workload: List[Tuple[str, ...]]) -> None:
    """
    Run the same workload on all required allocation algorithms.

    Args:
        total_memory (int): Total memory size in MB.
        workload (List[Tuple[str, ...]]): Workload operations.
    """
    algorithms = ["first_fit", "next_fit", "best_fit", "worst_fit"]

    for algorithm in algorithms:
        manager = MemoryManager(total_memory=total_memory, algorithm=algorithm)
        manager.run_workload(workload)
        manager.print_logs()


def main() -> None:
    """
    Main entry point.
    """
    total_memory = 256  # MB

    # Workload format:
    # ("A", process_id, size) -> allocate
    # ("D", process_id)       -> deallocate
    workload = [
        ("A", "A", 40),
        ("A", "B", 25),
        ("A", "C", 60),
        ("D", "B"),
        ("A", "D", 20),
        ("A", "E", 35),
        ("D", "A"),
        ("A", "F", 15),
        ("D", "C"),
        ("A", "G", 50),
        ("A", "H", 30),
        ("D", "D"),
        ("D", "F"),
        ("A", "I", 18),
        ("A", "J", 70),
    ]

    run_all_algorithms(total_memory, workload)


if __name__ == "__main__":
    main()
