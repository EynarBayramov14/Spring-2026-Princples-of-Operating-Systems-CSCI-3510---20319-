#!/usr/bin/env python3
"""
Operating Systems Assignment 3
File System Allocation Simulator

Implements and compares three file block allocation strategies:
  1) Contiguous allocation
  2) FAT-style linked allocation using an in-memory table
  3) I-node allocation with direct + indirect pointers

Supported operations:
  - MKDIR <path>
  - CREATE <path> [size] [initial_data]
  - DELETE <path>
  - OPEN <path>
  - CLOSE <fd>
  - READ <fd> <offset> <length>
  - WRITE <fd> <offset> <data>
  - LINK <target> <link_path>
  - SYMLINK <target> <link_path>
  - LS [path]
  - STAT <path>
  - STATUS
  - JOURNAL
  - CRASH_DELETE <path>   # logs delete intent and simulates crash before completion
  - RECOVER               # replays unfinished journal operations

Example:
  python fs_simulator_truly_final.py --algo contiguous --demo
  python fs_simulator_truly_final.py --algo fat --interactive
  python fs_simulator_truly_final.py --algo inode --workload workload.txt
"""

from __future__ import annotations

import argparse
import os
import shlex
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union


# ============================================================
# Exceptions
# ============================================================


class FileSystemError(Exception):
    pass


class AllocationError(FileSystemError):
    pass


class PathResolutionError(FileSystemError):
    pass


class InvalidOperationError(FileSystemError):
    pass


class NotDirectoryError(FileSystemError):
    pass


# ============================================================
# Helpers
# ============================================================


def ceil_div(a: int, b: int) -> int:
    return (a + b - 1) // b


def normalize_path(path: str) -> str:
    if not path:
        raise PathResolutionError("Empty path is invalid")
    if not path.startswith("/"):
        raise PathResolutionError(f"Path must be absolute: {path}")
    parts: List[str] = []
    for piece in path.split("/"):
        if piece in ("", "."):
            continue
        if piece == "..":
            if parts:
                parts.pop()
            continue
        parts.append(piece)
    return "/" + "/".join(parts)


def split_parent(path: str) -> Tuple[str, str]:
    path = normalize_path(path)
    if path == "/":
        raise PathResolutionError("Root has no parent")
    parent, name = os.path.split(path)
    if not parent:
        parent = "/"
    if not name:
        raise PathResolutionError(f"Invalid path: {path}")
    return parent, name


# ============================================================
# Journal
# ============================================================


@dataclass
class JournalEntry:
    txn_id: int
    op: str
    details: Dict[str, Union[str, int, List[int], List[str], bool]]
    committed: bool = False
    aborted: bool = False


class Journal:
    def __init__(self) -> None:
        self.entries: List[JournalEntry] = []
        self.next_txn_id = 1

    def begin(self, op: str, details: Dict[str, Union[str, int, List[int], List[str], bool]]) -> JournalEntry:
        entry = JournalEntry(txn_id=self.next_txn_id, op=op, details=details)
        self.next_txn_id += 1
        self.entries.append(entry)
        return entry

    def commit(self, entry: JournalEntry) -> None:
        entry.committed = True
        entry.aborted = False

    def abort(self, entry: JournalEntry) -> None:
        entry.aborted = True
        entry.committed = False

    def pending_entries(self) -> List[JournalEntry]:
        return [e for e in self.entries if not e.committed and not e.aborted]

    def render(self) -> str:
        lines = ["JOURNAL"]
        if not self.entries:
            lines.append("  <empty>")
            return "\n".join(lines)
        for e in self.entries:
            if e.committed:
                state = "COMMITTED"
            elif e.aborted:
                state = "ABORTED"
            else:
                state = "PENDING"
            lines.append(f"  txn={e.txn_id} op={e.op} state={state} details={e.details}")
        return "\n".join(lines)


# ============================================================
# Disk
# ============================================================


class Disk:
    """Linear array of fixed-size blocks."""

    def __init__(self, total_blocks: int, block_size: int) -> None:
        if total_blocks <= 0 or block_size <= 0:
            raise ValueError("total_blocks and block_size must be positive")
        self.total_blocks = total_blocks
        self.block_size = block_size
        self.free_map: List[bool] = [True] * total_blocks
        self.blocks: List[bytearray] = [bytearray(block_size) for _ in range(total_blocks)]

    def count_free(self) -> int:
        return sum(1 for x in self.free_map if x)

    def is_free(self, idx: int) -> bool:
        return self.free_map[idx]

    def allocate_specific(self, idx: int) -> None:
        if not (0 <= idx < self.total_blocks):
            raise AllocationError(f"Block index out of range: {idx}")
        if not self.free_map[idx]:
            raise AllocationError(f"Block already allocated: {idx}")
        self.free_map[idx] = False

    def free_specific(self, idx: int) -> None:
        if 0 <= idx < self.total_blocks:
            self.free_map[idx] = True
            self.blocks[idx] = bytearray(self.block_size)

    def free_blocks(self, indices: List[int]) -> None:
        for idx in indices:
            self.free_specific(idx)

    def all_free_runs(self) -> List[Tuple[int, int]]:
        runs: List[Tuple[int, int]] = []
        i = 0
        while i < self.total_blocks:
            if self.free_map[i]:
                start = i
                while i < self.total_blocks and self.free_map[i]:
                    i += 1
                runs.append((start, i - start))
            else:
                i += 1
        return runs

    def largest_free_run(self) -> int:
        return max((length for _, length in self.all_free_runs()), default=0)

    def external_fragmentation_ratio(self) -> float:
        free_blocks = self.count_free()
        if free_blocks == 0:
            return 0.0
        return 1.0 - (self.largest_free_run() / free_blocks)

    def write_content(self, block_indices: List[int], data: bytes) -> None:
        for idx in block_indices:
            self.blocks[idx] = bytearray(self.block_size)
        offset = 0
        for idx in block_indices:
            chunk = data[offset: offset + self.block_size]
            self.blocks[idx][: len(chunk)] = chunk
            offset += self.block_size
            if offset >= len(data):
                break

    def read_content(self, block_indices: List[int], size: int) -> bytes:
        buf = bytearray()
        for idx in block_indices:
            buf.extend(self.blocks[idx])
        return bytes(buf[:size])


# ============================================================
# Metadata
# ============================================================


@dataclass
class FileRecord:
    inode_id: int
    kind: str = "file"  # file | symlink
    size: int = 0
    link_count: int = 1
    open_count: int = 0
    namespace_refs: int = 1
    deleted: bool = False
    content: bytearray = field(default_factory=bytearray)
    symlink_target: Optional[str] = None

    # Generic allocated data blocks for this file object
    blocks: List[int] = field(default_factory=list)

    # Contiguous metadata
    contiguous_start: Optional[int] = None
    contiguous_length: int = 0

    # FAT metadata
    fat_first_block: Optional[int] = None

    # I-node metadata
    direct_blocks: List[int] = field(default_factory=list)
    indirect_block: Optional[int] = None  # metadata block storing pointers
    indirect_data_blocks: List[int] = field(default_factory=list)
    inode_loaded: bool = False


@dataclass
class DirNode:
    name: str
    parent: Optional["DirNode"]
    entries: Dict[str, Union["DirNode", FileRecord]] = field(default_factory=dict)

    def full_path(self) -> str:
        if self.parent is None:
            return "/"
        parts: List[str] = []
        cur: Optional[DirNode] = self
        while cur is not None and cur.parent is not None:
            parts.append(cur.name)
            cur = cur.parent
        return "/" + "/".join(reversed(parts))


# ============================================================
# Allocation strategies
# ============================================================


class AllocationStrategy:
    name = "base"

    def __init__(self, disk: Disk) -> None:
        self.disk = disk

    def allocate_for_new_file(self, record: FileRecord, required_blocks: int) -> None:
        raise NotImplementedError

    def resize_file(self, record: FileRecord, required_blocks: int) -> None:
        raise NotImplementedError

    def free_file(self, record: FileRecord) -> None:
        raise NotImplementedError

    def file_block_chain(self, record: FileRecord) -> List[int]:
        raise NotImplementedError

    def memory_overhead_bytes(self, fs: "FileSystemSimulator") -> int:
        return 0

    def read_cost(self, record: FileRecord) -> str:
        raise NotImplementedError

    def on_open(self, record: FileRecord) -> None:
        pass

    def on_close(self, record: FileRecord) -> None:
        pass

    def allocator_details(self, record: FileRecord) -> Dict[str, Union[str, int, List[int], None, bool]]:
        return {"blocks": self.file_block_chain(record), "read_cost": self.read_cost(record)}


class ContiguousAllocation(AllocationStrategy):
    name = "contiguous"

    def _find_run(self, length: int) -> Optional[int]:
        for start, run_len in self.disk.all_free_runs():
            if run_len >= length:
                return start
        return None

    def _assign_run(self, record: FileRecord, start: int, length: int) -> None:
        for idx in range(start, start + length):
            self.disk.allocate_specific(idx)
        record.contiguous_start = start
        record.contiguous_length = length
        record.blocks = list(range(start, start + length))

    def allocate_for_new_file(self, record: FileRecord, required_blocks: int) -> None:
        record.blocks = []
        record.contiguous_start = None
        record.contiguous_length = 0
        if required_blocks == 0:
            return
        start = self._find_run(required_blocks)
        if start is None:
            raise AllocationError(f"Contiguous allocation failed: no free run of {required_blocks} block(s)")
        self._assign_run(record, start, required_blocks)

    def resize_file(self, record: FileRecord, required_blocks: int) -> None:
        current = record.contiguous_length
        if current == required_blocks:
            return
        if required_blocks == 0:
            self.free_file(record)
            return
        if current == 0:
            self.allocate_for_new_file(record, required_blocks)
            return

        start = record.contiguous_start
        assert start is not None

        if required_blocks < current:
            to_free = list(range(start + required_blocks, start + current))
            self.disk.free_blocks(to_free)
            record.contiguous_length = required_blocks
            record.blocks = list(range(start, start + required_blocks))
            return

        extra = required_blocks - current
        can_expand = True
        for idx in range(start + current, start + current + extra):
            if idx >= self.disk.total_blocks or not self.disk.is_free(idx):
                can_expand = False
                break
        if can_expand:
            for idx in range(start + current, start + current + extra):
                self.disk.allocate_specific(idx)
            record.contiguous_length = required_blocks
            record.blocks = list(range(start, start + required_blocks))
            return

        old_blocks = list(record.blocks)
        old_data = self.disk.read_content(old_blocks, record.size)
        self.free_file(record)
        try:
            self.allocate_for_new_file(record, required_blocks)
        except Exception:
            self.allocate_for_new_file(record, len(old_blocks))
            self.disk.write_content(record.blocks, old_data)
            raise
        self.disk.write_content(record.blocks, old_data)

    def free_file(self, record: FileRecord) -> None:
        self.disk.free_blocks(record.blocks)
        record.blocks = []
        record.contiguous_start = None
        record.contiguous_length = 0

    def file_block_chain(self, record: FileRecord) -> List[int]:
        return list(record.blocks)

    def read_cost(self, record: FileRecord) -> str:
        if not record.blocks:
            return "0 blocks; 0 seeks"
        return f"{len(record.blocks)} block(s); sequential read after 1 initial seek"

    def allocator_details(self, record: FileRecord) -> Dict[str, Union[str, int, List[int], None, bool]]:
        return {
            "method": "contiguous",
            "start": record.contiguous_start,
            "length": record.contiguous_length,
            "blocks": list(record.blocks),
            "read_cost": self.read_cost(record),
        }


class FATAllocation(AllocationStrategy):
    name = "fat"
    EOF = -1
    FREE = None

    def __init__(self, disk: Disk, fat_entry_size: int = 4) -> None:
        super().__init__(disk)
        self.fat: List[Optional[int]] = [self.FREE] * disk.total_blocks
        self.fat_entry_size = fat_entry_size

    def _allocate_n_blocks(self, n: int) -> List[int]:
        free_blocks = [i for i, free in enumerate(self.disk.free_map) if free]
        if len(free_blocks) < n:
            raise AllocationError(f"FAT allocation failed: need {n} free block(s), have {len(free_blocks)}")
        chosen = free_blocks[:n]
        for idx in chosen:
            self.disk.allocate_specific(idx)
        return chosen

    def _link_chain(self, blocks: List[int]) -> None:
        if not blocks:
            return
        for i in range(len(blocks) - 1):
            self.fat[blocks[i]] = blocks[i + 1]
        self.fat[blocks[-1]] = self.EOF

    def allocate_for_new_file(self, record: FileRecord, required_blocks: int) -> None:
        record.blocks = []
        record.fat_first_block = None
        if required_blocks == 0:
            return
        blocks = self._allocate_n_blocks(required_blocks)
        self._link_chain(blocks)
        record.blocks = blocks
        record.fat_first_block = blocks[0]

    def resize_file(self, record: FileRecord, required_blocks: int) -> None:
        current = len(record.blocks)
        if current == required_blocks:
            return
        if required_blocks == 0:
            self.free_file(record)
            return
        if current == 0:
            self.allocate_for_new_file(record, required_blocks)
            return

        if required_blocks < current:
            keep = record.blocks[:required_blocks]
            drop = record.blocks[required_blocks:]
            if keep:
                self.fat[keep[-1]] = self.EOF
            for idx in drop:
                self.fat[idx] = self.FREE
            self.disk.free_blocks(drop)
            record.blocks = keep
            record.fat_first_block = keep[0] if keep else None
            return

        extra = self._allocate_n_blocks(required_blocks - current)
        self.fat[record.blocks[-1]] = extra[0]
        self._link_chain(extra)
        record.blocks.extend(extra)
        record.fat_first_block = record.blocks[0]

    def free_file(self, record: FileRecord) -> None:
        for idx in record.blocks:
            self.fat[idx] = self.FREE
        self.disk.free_blocks(record.blocks)
        record.blocks = []
        record.fat_first_block = None

    def file_block_chain(self, record: FileRecord) -> List[int]:
        chain: List[int] = []
        current = record.fat_first_block
        seen = set()
        while current is not None and current != self.EOF:
            if current in seen:
                raise FileSystemError("FAT cycle detected")
            seen.add(current)
            chain.append(current)
            nxt = self.fat[current]
            if nxt == self.EOF:
                break
            current = nxt
        return chain

    def memory_overhead_bytes(self, fs: "FileSystemSimulator") -> int:
        return len(self.fat) * self.fat_entry_size

    def read_cost(self, record: FileRecord) -> str:
        n = len(record.blocks)
        if n == 0:
            return "0 blocks; 0 pointer traversals"
        return f"{n} block(s); follow FAT chain in memory across {max(0, n - 1)} link(s)"

    def allocator_details(self, record: FileRecord) -> Dict[str, Union[str, int, List[int], None, bool]]:
        return {
            "method": "fat",
            "first_block": record.fat_first_block,
            "chain": self.file_block_chain(record),
            "fat_memory_overhead_bytes": len(self.fat) * self.fat_entry_size,
            "read_cost": self.read_cost(record),
        }


class InodeAllocation(AllocationStrategy):
    name = "inode"

    def __init__(self, disk: Disk, direct_ptrs: int = 4, ptr_size: int = 4, inode_base_size: int = 64) -> None:
        super().__init__(disk)
        self.direct_ptrs = direct_ptrs
        self.ptr_size = ptr_size
        self.inode_base_size = inode_base_size
        self.indirect_capacity = disk.block_size // ptr_size

    def _max_data_blocks(self) -> int:
        return self.direct_ptrs + self.indirect_capacity

    def _needs_indirect(self, data_blocks: int) -> bool:
        return data_blocks > self.direct_ptrs

    def _allocate_n_blocks(self, n: int) -> List[int]:
        free_blocks = [i for i, free in enumerate(self.disk.free_map) if free]
        if len(free_blocks) < n:
            raise AllocationError(f"I-node allocation failed: need {n} free block(s), have {len(free_blocks)}")
        chosen = free_blocks[:n]
        for idx in chosen:
            self.disk.allocate_specific(idx)
        return chosen

    def _write_indirect_block(self, record: FileRecord) -> None:
        record.direct_blocks = list(record.blocks[: self.direct_ptrs])
        overflow = list(record.blocks[self.direct_ptrs:])
        record.indirect_data_blocks = overflow

        if overflow:
            if record.indirect_block is None:
                raise AllocationError("Internal error: indirect block missing for overflow data")
            buf = bytearray(self.disk.block_size)
            for i, block_num in enumerate(overflow):
                start = i * self.ptr_size
                buf[start:start + self.ptr_size] = int(block_num).to_bytes(self.ptr_size, "little", signed=False)
            self.disk.blocks[record.indirect_block] = buf
        else:
            if record.indirect_block is not None:
                self.disk.blocks[record.indirect_block] = bytearray(self.disk.block_size)

    def allocate_for_new_file(self, record: FileRecord, required_blocks: int) -> None:
        if required_blocks > self._max_data_blocks():
            raise AllocationError(
                f"File too large for this simulator's i-node layout: max data blocks = {self._max_data_blocks()}"
            )

        record.blocks = []
        record.direct_blocks = []
        record.indirect_data_blocks = []
        if record.indirect_block is not None:
            self.disk.free_specific(record.indirect_block)
            record.indirect_block = None

        total_needed = required_blocks + (1 if self._needs_indirect(required_blocks) else 0)
        if total_needed == 0:
            return

        chosen = self._allocate_n_blocks(total_needed)
        if self._needs_indirect(required_blocks):
            record.blocks = chosen[:required_blocks]
            record.indirect_block = chosen[-1]
        else:
            record.blocks = chosen
            record.indirect_block = None
        self._write_indirect_block(record)

    def resize_file(self, record: FileRecord, required_blocks: int) -> None:
        if required_blocks > self._max_data_blocks():
            raise AllocationError(
                f"File too large for this simulator's i-node layout: max data blocks = {self._max_data_blocks()}"
            )

        current = len(record.blocks)
        if current == required_blocks:
            return
        if required_blocks == 0:
            self.free_file(record)
            return
        if current == 0:
            self.allocate_for_new_file(record, required_blocks)
            return

        current_needs_indirect = record.indirect_block is not None
        target_needs_indirect = self._needs_indirect(required_blocks)

        # Growth path: allocate all needed blocks before mutating state.
        if required_blocks > current:
            extra_data = required_blocks - current
            extra_meta = 1 if target_needs_indirect and not current_needs_indirect else 0
            extras = self._allocate_n_blocks(extra_data + extra_meta)
            if extra_meta:
                record.blocks.extend(extras[:extra_data])
                record.indirect_block = extras[-1]
            else:
                record.blocks.extend(extras)
            self._write_indirect_block(record)
            return

        # Shrink path.
        keep = record.blocks[:required_blocks]
        drop = record.blocks[required_blocks:]
        self.disk.free_blocks(drop)
        record.blocks = keep

        if current_needs_indirect and not target_needs_indirect:
            assert record.indirect_block is not None
            self.disk.free_specific(record.indirect_block)
            record.indirect_block = None

        self._write_indirect_block(record)

    def free_file(self, record: FileRecord) -> None:
        self.disk.free_blocks(record.blocks)
        record.blocks = []
        if record.indirect_block is not None:
            self.disk.free_specific(record.indirect_block)
        record.direct_blocks = []
        record.indirect_block = None
        record.indirect_data_blocks = []

    def file_block_chain(self, record: FileRecord) -> List[int]:
        return list(record.blocks)

    def memory_overhead_bytes(self, fs: "FileSystemSimulator") -> int:
        loaded = sum(1 for rec in fs.records.values() if rec.inode_loaded)
        per_loaded_inode = self.inode_base_size + (self.direct_ptrs + 1) * self.ptr_size
        return loaded * per_loaded_inode

    def on_open(self, record: FileRecord) -> None:
        record.inode_loaded = True

    def on_close(self, record: FileRecord) -> None:
        if record.open_count == 0:
            record.inode_loaded = False

    def read_cost(self, record: FileRecord) -> str:
        n = len(record.blocks)
        if n == 0:
            return "0 blocks; inode lookup only"
        direct = min(n, self.direct_ptrs)
        indirect = max(0, n - self.direct_ptrs)
        if indirect == 0:
            return f"{n} block(s); read through inode direct pointers"
        return f"{n} block(s); {direct} direct block(s) + {indirect} block(s) via one indirect pointer block"

    def allocator_details(self, record: FileRecord) -> Dict[str, Union[str, int, List[int], None, bool]]:
        return {
            "method": "inode",
            "direct_blocks": list(record.direct_blocks),
            "indirect_block": record.indirect_block,
            "indirect_data_blocks": list(record.indirect_data_blocks),
            "all_data_blocks": list(record.blocks),
            "inode_loaded": record.inode_loaded,
            "read_cost": self.read_cost(record),
        }


# ============================================================
# File system simulator
# ============================================================


class FileSystemSimulator:
    def __init__(self, total_blocks: int, block_size: int, algorithm: str) -> None:
        self.disk = Disk(total_blocks, block_size)
        self.journal = Journal()
        self.root = DirNode(name="", parent=None)
        self.records: Dict[int, FileRecord] = {}
        self.next_inode_id = 1
        self.open_table: Dict[int, FileRecord] = {}
        self.next_fd = 3

        algo = algorithm.lower()
        if algo == "contiguous":
            self.allocator: AllocationStrategy = ContiguousAllocation(self.disk)
        elif algo == "fat":
            self.allocator = FATAllocation(self.disk)
        elif algo == "inode":
            self.allocator = InodeAllocation(self.disk)
        else:
            raise ValueError(f"Unknown algorithm: {algorithm}")

    # ---------------- path resolution ----------------

    def _resolve(self, path: str, follow_symlinks: bool = True, symlink_limit: int = 20) -> Union[DirNode, FileRecord]:
        path = normalize_path(path)
        if path == "/":
            return self.root
        parts = [p for p in path.strip("/").split("/") if p]
        current: Union[DirNode, FileRecord] = self.root

        for i, part in enumerate(parts):
            if not isinstance(current, DirNode):
                raise NotDirectoryError(f"Component is not a directory before: {part}")
            if part not in current.entries:
                raise PathResolutionError(f"Path not found: {path}")
            current = current.entries[part]
            is_last = i == len(parts) - 1

            if isinstance(current, FileRecord) and current.kind == "symlink" and follow_symlinks:
                if symlink_limit <= 0:
                    raise PathResolutionError("Too many symbolic link resolutions")
                target = current.symlink_target
                if target is None:
                    raise PathResolutionError(f"Broken symbolic link: {path}")
                remaining = parts[i + 1:]
                target_path = normalize_path(target)
                if remaining:
                    target_path = normalize_path(target_path + "/" + "/".join(remaining))
                return self._resolve(target_path, follow_symlinks=True, symlink_limit=symlink_limit - 1)

            if isinstance(current, FileRecord) and not is_last:
                raise NotDirectoryError(f"Component is not a directory in: {path}")
        return current

    def _resolve_parent(self, path: str) -> Tuple[DirNode, str]:
        parent_path, name = split_parent(path)
        parent = self._resolve(parent_path)
        if not isinstance(parent, DirNode):
            raise NotDirectoryError(f"Parent is not a directory: {parent_path}")
        return parent, name

    def _ensure_directory(self, path: str) -> DirNode:
        node = self._resolve(path)
        if not isinstance(node, DirNode):
            raise NotDirectoryError(f"Not a directory: {path}")
        return node

    def _new_inode(self, kind: str = "file") -> FileRecord:
        record = FileRecord(inode_id=self.next_inode_id, kind=kind)
        self.records[self.next_inode_id] = record
        self.next_inode_id += 1
        return record

    def _cleanup_if_unreferenced(self, record: FileRecord) -> bool:
        if record.namespace_refs == 0 and record.open_count == 0:
            self.allocator.free_file(record)
            self.records.pop(record.inode_id, None)
            return True
        return False

    # ---------------- operations ----------------

    def mkdir(self, path: str) -> str:
        parent, name = self._resolve_parent(path)
        if name in parent.entries:
            raise InvalidOperationError(f"Entry already exists: {path}")
        parent.entries[name] = DirNode(name=name, parent=parent)
        return f"MKDIR {path}: created"

    def create(self, path: str, size: int = 0, initial_data: str = "") -> str:
        if size < 0:
            raise InvalidOperationError("File size cannot be negative")
        parent, name = self._resolve_parent(path)
        if name in parent.entries:
            raise InvalidOperationError(f"Entry already exists: {path}")

        record = self._new_inode(kind="file")
        data = initial_data.encode("utf-8") if initial_data else b"\x00" * size
        if initial_data and len(data) < size:
            data = data + b"\x00" * (size - len(data))
        elif initial_data and len(data) > size:
            size = len(data)

        required_blocks = ceil_div(size, self.disk.block_size)
        try:
            self.allocator.allocate_for_new_file(record, required_blocks)
        except Exception:
            self.records.pop(record.inode_id, None)
            raise

        record.size = size
        record.content = bytearray(data[:size])
        if required_blocks:
            self.disk.write_content(self.allocator.file_block_chain(record), bytes(record.content))

        parent.entries[name] = record
        return f"CREATE {path}: inode={record.inode_id}, size={record.size}, blocks={self.allocator.file_block_chain(record)}"

    def open(self, path: str) -> str:
        node = self._resolve(path)
        if isinstance(node, DirNode):
            raise InvalidOperationError("Cannot open a directory")
        if node.kind == "symlink":
            resolved = self._resolve(path, follow_symlinks=True)
            if isinstance(resolved, DirNode):
                raise InvalidOperationError("Cannot open a directory")
            node = resolved
        fd = self.next_fd
        self.next_fd += 1
        node.open_count += 1
        self.allocator.on_open(node)
        self.open_table[fd] = node
        return f"OPEN {path}: fd={fd}, inode={node.inode_id}"

    def close(self, fd: int) -> str:
        if fd not in self.open_table:
            raise InvalidOperationError(f"Invalid fd: {fd}")
        record = self.open_table.pop(fd)
        record.open_count -= 1
        self.allocator.on_close(record)
        cleaned = self._cleanup_if_unreferenced(record)
        if cleaned:
            return f"CLOSE fd={fd}: inode={record.inode_id} closed and deferred deletion completed"
        return f"CLOSE fd={fd}: closed inode={record.inode_id}"

    def read(self, fd: int, offset: int, length: int) -> str:
        if fd not in self.open_table:
            raise InvalidOperationError(f"Invalid fd: {fd}")
        if offset < 0 or length < 0:
            raise InvalidOperationError("Offset and length must be non-negative")
        record = self.open_table[fd]
        end = min(offset + length, record.size)
        data = bytes(record.content[offset:end]).decode("utf-8", errors="replace")
        cost = self.allocator.read_cost(record)
        return f"READ fd={fd} offset={offset} length={length}: data={data!r}; performance={cost}"

    def write(self, fd: int, offset: int, data: str) -> str:
        if fd not in self.open_table:
            raise InvalidOperationError(f"Invalid fd: {fd}")
        if offset < 0:
            raise InvalidOperationError("Offset must be non-negative")
        record = self.open_table[fd]
        payload = data.encode("utf-8")
        new_size = max(record.size, offset + len(payload))
        needed_blocks = ceil_div(new_size, self.disk.block_size)
        old_size = record.size
        self.allocator.resize_file(record, needed_blocks)
        if len(record.content) < new_size:
            record.content.extend(b"\x00" * (new_size - len(record.content)))
        record.content[offset: offset + len(payload)] = payload
        record.size = new_size
        record.content = record.content[:new_size]
        if needed_blocks:
            self.disk.write_content(self.allocator.file_block_chain(record), bytes(record.content))
        return f"WRITE fd={fd} offset={offset} bytes={len(payload)}: size {old_size}->{record.size}, blocks={self.allocator.file_block_chain(record)}"

    def link(self, target: str, link_path: str) -> str:
        record = self._resolve(target)
        if isinstance(record, DirNode):
            raise InvalidOperationError("Hard links to directories are not supported")
        if record.kind == "symlink":
            raise InvalidOperationError("Hard links to symbolic-link objects are not supported")
        parent, name = self._resolve_parent(link_path)
        if name in parent.entries:
            raise InvalidOperationError(f"Entry already exists: {link_path}")
        parent.entries[name] = record
        record.link_count += 1
        record.namespace_refs += 1
        return f"LINK {link_path} -> {target}: hard link created, inode={record.inode_id}, refcount={record.link_count}"

    def symlink(self, target: str, link_path: str) -> str:
        parent, name = self._resolve_parent(link_path)
        if name in parent.entries:
            raise InvalidOperationError(f"Entry already exists: {link_path}")
        link_record = self._new_inode(kind="symlink")
        link_record.symlink_target = normalize_path(target)
        link_record.size = len(link_record.symlink_target.encode("utf-8"))
        link_record.content = bytearray(link_record.symlink_target.encode("utf-8"))
        required_blocks = ceil_div(link_record.size, self.disk.block_size)
        try:
            self.allocator.allocate_for_new_file(link_record, required_blocks)
        except Exception:
            self.records.pop(link_record.inode_id, None)
            raise
        if required_blocks:
            self.disk.write_content(self.allocator.file_block_chain(link_record), bytes(link_record.content))
        parent.entries[name] = link_record
        return f"SYMLINK {link_path} -> {target}: created symlink inode={link_record.inode_id}"

    def _begin_delete_journal(self, path: str, target: Union[DirNode, FileRecord]) -> JournalEntry:
        inode_id = target.inode_id if isinstance(target, FileRecord) else -1
        blocks = [] if isinstance(target, DirNode) else list(self.allocator.file_block_chain(target))
        return self.journal.begin(
            "DELETE",
            {
                "path": normalize_path(path),
                "inode_id": inode_id,
                "steps": [
                    "remove from directory",
                    "release inode if final reference",
                    "return disk blocks if final reference",
                ],
                "blocks": blocks,
            },
        )

    def delete(self, path: str) -> str:
        return self._delete_internal(path, simulate_crash=False)

    def crash_delete(self, path: str) -> str:
        return self._delete_internal(path, simulate_crash=True)

    def _delete_internal(self, path: str, simulate_crash: bool) -> str:
        parent, name = self._resolve_parent(path)
        if name not in parent.entries:
            raise PathResolutionError(f"Path not found: {path}")
        target = parent.entries[name]

        # Directory correctness: reject non-empty directory before journaling or mutation.
        if isinstance(target, DirNode):
            if target.entries:
                raise InvalidOperationError("Cannot delete a non-empty directory")
            log = self._begin_delete_journal(path, target)
            del parent.entries[name]
            if simulate_crash:
                return f"CRASH_DELETE {path}: simulated crash after removing empty directory entry; run RECOVER"
            self.journal.commit(log)
            return f"DELETE {path}: empty directory removed"

        log = self._begin_delete_journal(path, target)
        del parent.entries[name]
        target.namespace_refs -= 1

        # Symbolic link is its own file and inode.
        if target.kind == "symlink":
            if simulate_crash:
                return f"CRASH_DELETE {path}: simulated crash after namespace removal of symlink; run RECOVER"
            self.allocator.free_file(target)
            self.records.pop(target.inode_id, None)
            self.journal.commit(log)
            return f"DELETE {path}: symbolic link removed"

        # Hard-linked regular file.
        target.link_count -= 1
        if target.link_count > 0:
            if simulate_crash:
                return f"CRASH_DELETE {path}: simulated crash after removing one hard link; remaining_refcount={target.link_count}; run RECOVER"
            self.journal.commit(log)
            return f"DELETE {path}: removed one hard link, inode={target.inode_id}, remaining_refcount={target.link_count}"

        target.deleted = True
        if simulate_crash:
            return f"CRASH_DELETE {path}: simulated crash after final-name removal; run RECOVER"

        if target.open_count > 0:
            self.journal.commit(log)
            return f"DELETE {path}: namespace entry removed; inode={target.inode_id} is still open, blocks will be released after final CLOSE"

        self.allocator.free_file(target)
        self.records.pop(target.inode_id, None)
        self.journal.commit(log)
        return f"DELETE {path}: file removed, inode released, blocks returned={log.details['blocks']}"

    def recover(self) -> str:
        pending = self.journal.pending_entries()
        if not pending:
            return "RECOVER: no pending journal entries"

        recovered_msgs: List[str] = []
        for entry in pending:
            if entry.op != "DELETE":
                self.journal.commit(entry)
                recovered_msgs.append(f"txn={entry.txn_id}: unsupported op marked committed")
                continue

            inode_id = int(entry.details["inode_id"])
            path = str(entry.details["path"])

            if inode_id == -1:
                self.journal.commit(entry)
                recovered_msgs.append(f"txn={entry.txn_id}: completed delete of directory {path}")
                continue

            record = self.records.get(inode_id)
            if record is None:
                self.journal.commit(entry)
                recovered_msgs.append(f"txn={entry.txn_id}: inode already absent; nothing to do")
                continue

            if record.kind == "symlink":
                self.allocator.free_file(record)
                self.records.pop(record.inode_id, None)
                self.journal.commit(entry)
                recovered_msgs.append(f"txn={entry.txn_id}: replayed symlink deletion for {path}")
                continue

            if record.link_count > 0:
                self.journal.commit(entry)
                recovered_msgs.append(f"txn={entry.txn_id}: finalized hard-link removal for {path}; inode={record.inode_id} preserved")
                continue

            record.deleted = True
            if record.open_count == 0:
                self.allocator.free_file(record)
                self.records.pop(record.inode_id, None)
                recovered_msgs.append(f"txn={entry.txn_id}: freed inode={inode_id} and blocks for {path}")
            else:
                recovered_msgs.append(f"txn={entry.txn_id}: inode={inode_id} still open; deferred cleanup until final CLOSE")
            self.journal.commit(entry)

        return "RECOVER:\n  " + "\n  ".join(recovered_msgs)

    # ---------------- queries ----------------

    def ls(self, path: str = "/") -> str:
        node = self._ensure_directory(path)
        lines = [f"LS {normalize_path(path)}"]
        for name in sorted(node.entries):
            entry = node.entries[name]
            if isinstance(entry, DirNode):
                lines.append(f"  [DIR]  {name}/")
            elif entry.kind == "symlink":
                status = "OK"
                try:
                    self._resolve(entry.symlink_target or "/")
                except Exception:
                    status = "BROKEN"
                lines.append(f"  [SYM]  {name} -> {entry.symlink_target} [{status}]")
            else:
                lines.append(f"  [FILE] {name} (inode={entry.inode_id}, size={entry.size}, links={entry.link_count}, open={entry.open_count})")
        if len(lines) == 1:
            lines.append("  <empty>")
        return "\n".join(lines)

    def stat(self, path: str) -> str:
        parent, name = self._resolve_parent(path)
        if name not in parent.entries:
            raise PathResolutionError(f"Path not found: {path}")
        entry = parent.entries[name]
        if isinstance(entry, DirNode):
            return f"STAT {path}: type=directory, entries={len(entry.entries)}"
        details = self.allocator.allocator_details(entry)
        return f"STAT {path}: type={entry.kind}, inode={entry.inode_id}, size={entry.size}, links={entry.link_count}, namespace_refs={entry.namespace_refs}, open={entry.open_count}, deleted={entry.deleted}, details={details}"

    def status(self) -> str:
        lines = [
            f"STATUS algorithm={self.allocator.name}",
            f"  total_blocks={self.disk.total_blocks}",
            f"  block_size={self.disk.block_size}",
            f"  free_blocks={self.disk.count_free()}",
            f"  used_blocks={self.disk.total_blocks - self.disk.count_free()}",
            f"  largest_free_run={self.disk.largest_free_run()}",
            f"  free_runs={self.disk.all_free_runs()}",
            f"  memory_overhead_bytes={self.allocator.memory_overhead_bytes(self)}",
            f"  loaded_open_inodes={sum(1 for r in self.records.values() if r.inode_loaded)}",
            f"  open_fds={sorted(self.open_table.keys())}",
            f"  pending_journal_entries={len(self.journal.pending_entries())}",
        ]
        if self.allocator.name == "contiguous":
            lines.append(f"  external_fragmentation_ratio={self.disk.external_fragmentation_ratio():.4f}")
        return "\n".join(lines)

    def journal_status(self) -> str:
        return self.journal.render()

    # ---------------- command execution ----------------

    def execute(self, line: str) -> Optional[str]:
        line = line.strip()
        if not line or line.startswith("#"):
            return None
        parts = shlex.split(line)
        if not parts:
            return None
        cmd = parts[0].upper()
        try:
            if cmd == "MKDIR":
                return self.mkdir(parts[1])
            if cmd == "CREATE":
                path = parts[1]
                size = int(parts[2]) if len(parts) >= 3 else 0
                data = parts[3] if len(parts) >= 4 else ""
                return self.create(path, size=size, initial_data=data)
            if cmd == "DELETE":
                return self.delete(parts[1])
            if cmd == "CRASH_DELETE":
                return self.crash_delete(parts[1])
            if cmd == "OPEN":
                return self.open(parts[1])
            if cmd == "CLOSE":
                return self.close(int(parts[1]))
            if cmd == "READ":
                return self.read(int(parts[1]), int(parts[2]), int(parts[3]))
            if cmd == "WRITE":
                fd = int(parts[1])
                offset = int(parts[2])
                data = " ".join(parts[3:])
                return self.write(fd, offset, data)
            if cmd == "LINK":
                return self.link(parts[1], parts[2])
            if cmd == "SYMLINK":
                return self.symlink(parts[1], parts[2])
            if cmd == "LS":
                return self.ls(parts[1] if len(parts) >= 2 else "/")
            if cmd == "STAT":
                return self.stat(parts[1])
            if cmd == "STATUS":
                return self.status()
            if cmd == "JOURNAL":
                return self.journal_status()
            if cmd == "RECOVER":
                return self.recover()
            raise InvalidOperationError(f"Unknown command: {cmd}")
        except Exception as exc:
            return f"ERROR {cmd}: {exc}"


# ============================================================
# Demo workload
# ============================================================


DEMO_WORKLOAD = [
    "MKDIR /docs",
    "CREATE /docs/a.txt 20 hello_world_demo",
    "OPEN /docs/a.txt",
    "WRITE 3 5 __OS__",
    "READ 3 0 20",
    "LINK /docs/a.txt /docs/a_hard.txt",
    "SYMLINK /docs/a.txt /docs/a_soft.txt",
    "STAT /docs/a.txt",
    "DELETE /docs/a.txt",
    "STAT /docs/a_hard.txt",
    "DELETE /docs/a_soft.txt",
    "CLOSE 3",
    "STATUS",
    "LS /docs",
    "JOURNAL",
]


# ============================================================
# CLI
# ============================================================


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="File system allocation simulator")
    parser.add_argument("--algo", choices=["contiguous", "fat", "inode"], required=True)
    parser.add_argument("--blocks", type=int, default=64, help="Total disk blocks")
    parser.add_argument("--block-size", type=int, default=16, help="Block size in bytes")
    parser.add_argument("--workload", type=str, help="Path to workload file")
    parser.add_argument("--interactive", action="store_true", help="Run interactive shell")
    parser.add_argument("--demo", action="store_true", help="Run built-in demo workload")
    return parser


def run_workload(fs: FileSystemSimulator, lines: List[str]) -> int:
    for line in lines:
        result = fs.execute(line)
        if result is not None:
            print(result)
    return 0


def interactive_shell(fs: FileSystemSimulator) -> int:
    print(f"Interactive mode started for algorithm={fs.allocator.name}. Type EXIT to quit.")
    while True:
        try:
            line = input("fs> ")
        except EOFError:
            print()
            break
        if line.strip().upper() in {"EXIT", "QUIT"}:
            break
        result = fs.execute(line)
        if result is not None:
            print(result)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    fs = FileSystemSimulator(total_blocks=args.blocks, block_size=args.block_size, algorithm=args.algo)

    ran_anything = False
    if args.workload:
        with open(args.workload, "r", encoding="utf-8") as f:
            lines = f.readlines()
        run_workload(fs, lines)
        ran_anything = True

    if args.demo:
        run_workload(fs, DEMO_WORKLOAD)
        ran_anything = True

    if args.interactive or not ran_anything:
        return interactive_shell(fs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
