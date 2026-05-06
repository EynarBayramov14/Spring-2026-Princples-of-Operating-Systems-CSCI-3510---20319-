"""
Assignment 4: I/O Resource Manager and Deadlock Detection Simulator

This program simulates the management of nonpreemptable I/O resources
and detects deadlocks using a graph-based Resource Allocation Graph (RAG).

Supported devices:
    Block devices    : e.g. BluRay, USB
    Character devices: e.g. Printer, Scanner

Each resource has exactly one instance and is nonpreemptable.

Input commands:

    RESOURCE <resource_id> <BLOCK|CHARACTER>   — register a new I/O device
    REQUEST  <process_id>  <resource_id>       — process requests a device
    RELEASE  <process_id>  <resource_id>       — process releases a device
    STATUS                                      — print full system state
    DETECT                                      — manually run deadlock check
    HELP                                        — show command reference
    EXIT                                        — quit interactive mode

Lines starting with # are treated as comments and ignored.

Usage:

    # Interactive mode (loads default resources automatically):
    python io_deadlock_simulator.py

    # File mode:
    python io_deadlock_simulator.py input.txt

Example input.txt:

    RESOURCE BluRay  BLOCK
    RESOURCE USB     BLOCK
    RESOURCE Printer CHARACTER
    RESOURCE Scanner CHARACTER

    REQUEST P1 Scanner
    REQUEST P2 BluRay
    REQUEST P1 BluRay
    REQUEST P2 Scanner
    STATUS
"""

from __future__ import annotations

from dataclasses import dataclass, field
from collections import defaultdict, deque
from typing import Dict, List, Optional, Set, Tuple
import sys


# ---------------------------------------------------------------------------
# Data Model
# ---------------------------------------------------------------------------

@dataclass
class Resource:
    """
    Represents a single nonpreemptable I/O device.

    Attributes:
        resource_id   : Unique name of the device (e.g. "Scanner").
        resource_type : "BLOCK" for block devices, "CHARACTER" for character devices.
        held_by       : ID of the process currently holding this resource,
                        or None if the resource is free.
    """
    resource_id: str
    resource_type: str
    held_by: Optional[str] = field(default=None)


# ---------------------------------------------------------------------------
# Resource Allocation Graph
# ---------------------------------------------------------------------------

class ResourceAllocationGraph:
    """
    Dynamic directed graph that models system resource state.

    Node types
    ----------
    P:<process_id>   Process node
    R:<resource_id>  Resource node

    Edge semantics
    --------------
    R:<resource_id>  ->  P:<process_id>
        The resource is currently allocated to the process.

    P:<process_id>   ->  R:<resource_id>
        The process is blocked and waiting for the resource.

    Deadlock detection
    ------------------
    A deadlock exists if and only if the RAG contains a directed cycle.
    The detection algorithm follows the specification exactly:

        Step 1  For each node N in the graph, use N as the starting node.
        Step 2  Initialise list L to empty; mark all arcs as unmarked.
        Step 3  Append the current node to L.
                If it now appears twice, a cycle has been found — terminate.
        Step 4  If there is an unmarked outgoing arc, go to Step 5.
                Otherwise go to Step 6.
        Step 5  Pick an unmarked arc, mark it, follow it, go to Step 3.
        Step 6  If this is the initial node — no cycle, terminate.
                Otherwise dead end — remove from L and backtrack.
    """

    def __init__(self) -> None:
        # adjacency[node] = set of successor nodes
        self.adjacency: Dict[str, Set[str]] = defaultdict(set)

    # ------------------------------------------------------------------
    # Node name helpers
    # ------------------------------------------------------------------

    @staticmethod
    def process_node(process_id: str) -> str:
        """Returns the canonical name for a process node."""
        return f"P:{process_id}"

    @staticmethod
    def resource_node(resource_id: str) -> str:
        """Returns the canonical name for a resource node."""
        return f"R:{resource_id}"

    @staticmethod
    def pretty_node(node: str) -> str:
        """Returns a human-readable label for a node."""
        if node.startswith("P:"):
            return f"Process {node[2:]}"
        if node.startswith("R:"):
            return f"Resource {node[2:]}"
        return node

    # ------------------------------------------------------------------
    # Graph mutation
    # ------------------------------------------------------------------

    def add_node(self, node: str) -> None:
        """Ensures the node exists in the adjacency map."""
        self.adjacency.setdefault(node, set())

    def add_edge(self, from_node: str, to_node: str) -> None:
        """Adds a directed edge and ensures both endpoints exist."""
        self.add_node(from_node)
        self.add_node(to_node)
        self.adjacency[from_node].add(to_node)

    def remove_edge(self, from_node: str, to_node: str) -> None:
        """Removes a directed edge if it exists; silently ignores absent edges."""
        if from_node in self.adjacency:
            self.adjacency[from_node].discard(to_node)

    # ------------------------------------------------------------------
    # Graph queries
    # ------------------------------------------------------------------

    def get_all_nodes(self) -> Set[str]:
        """Returns the set of all nodes (sources and destinations)."""
        nodes: Set[str] = set(self.adjacency.keys())
        for destinations in self.adjacency.values():
            nodes.update(destinations)
        return nodes

    def get_outgoing_edges(self, node: str) -> List[str]:
        """
        Returns the outgoing neighbours of a node in sorted order.

        The specification states the arc may be chosen at random.
        This implementation uses sorted order so that simulation output
        is deterministic and reproducible across grading runs.
        """
        return sorted(self.adjacency.get(node, set()))

    # ------------------------------------------------------------------
    # Cycle / deadlock detection
    # ------------------------------------------------------------------

    def detect_cycle(self) -> Tuple[bool, List[str]]:
        """
        Detects a directed cycle in the RAG (Step 1 of the specification).

        For each node in the graph a fresh DFS is started.
        Arc markings and the path list L are reset per starting node
        (Step 2 of the specification).

        Returns:
            (True,  cycle_path)  — deadlock detected; cycle_path is the list
                                   of nodes forming the cycle, starting and
                                   ending at the same node.
            (False, [])          — no cycle found.
        """
        all_nodes = sorted(self.get_all_nodes())

        for start_node in all_nodes:
            path: List[str] = []

            # visit_count[node] tracks how many times the node appears in
            # the current path list L.  This gives O(1) duplicate detection,
            # whereas list.count() would be O(n) per call.
            visit_count: Dict[str, int] = {}

            # first_occurrence[node] records the index in `path` where the
            # node was first appended.  Used to extract the cycle slice
            # without a second linear scan.
            first_occurrence: Dict[str, int] = {}

            # marked_arcs tracks which directed edges have already been
            # followed from the current start node (Step 2 / Step 5).
            marked_arcs: Set[Tuple[str, str]] = set()

            found, cycle = self._dfs(
                current_node=start_node,
                path=path,
                visit_count=visit_count,
                first_occurrence=first_occurrence,
                marked_arcs=marked_arcs,
            )

            if found:
                return True, cycle

        return False, []

    def _dfs(
        self,
        current_node: str,
        path: List[str],
        visit_count: Dict[str, int],
        first_occurrence: Dict[str, int],
        marked_arcs: Set[Tuple[str, str]],
    ) -> Tuple[bool, List[str]]:
        """
        Recursive DFS helper that implements Steps 3 – 6 of the specification.

        Steps 3: Append current_node to L; check for second occurrence.
        Steps 4-5: Iterate over unmarked outgoing arcs; mark and follow each.
        Step 6: Dead end — pop current_node from L and backtrack.

        Complexity: O(V + E) per starting node.
        """

        # Step 3: Add the current node to list L.
        path.append(current_node)
        visit_count[current_node] = visit_count.get(current_node, 0) + 1

        # Record the first time this node enters the path (for cycle slicing).
        if current_node not in first_occurrence:
            first_occurrence[current_node] = len(path) - 1

        # Step 3: If the node now appears twice in L, a cycle exists.
        if visit_count[current_node] == 2:
            # Extract the cycle: everything from the first occurrence onward.
            cycle = path[first_occurrence[current_node]:]
            return True, cycle

        # Steps 4 and 5: Explore unmarked outgoing arcs.
        for neighbor in self.get_outgoing_edges(current_node):
            arc = (current_node, neighbor)

            if arc not in marked_arcs:
                # Step 5: Mark the arc and follow it.
                marked_arcs.add(arc)

                found, cycle = self._dfs(
                    current_node=neighbor,
                    path=path,
                    visit_count=visit_count,
                    first_occurrence=first_occurrence,
                    marked_arcs=marked_arcs,
                )

                if found:
                    return True, cycle

        # Step 6: Dead end — remove this node from L and backtrack.
        path.pop()
        visit_count[current_node] -= 1

        # Note: first_occurrence is intentionally NOT cleared here.
        # The index becomes invalid once the node is popped, but it will
        # only be read again if the node is re-entered (visit_count == 2),
        # at which point the index in first_occurrence correctly marks where
        # the cycle began.

        return False, []


# ---------------------------------------------------------------------------
# I/O Resource Manager
# ---------------------------------------------------------------------------

class IOResourceManager:
    """
    Simulates an operating system I/O resource manager.

    Responsibilities:
        - Register block and character I/O devices.
        - Grant resources immediately when they are free.
        - Block processes when a requested resource is busy and maintain
          a FIFO waiting queue per resource.
        - Maintain the Resource Allocation Graph after every state change.
        - Automatically run deadlock detection after every blocked request.
        - Release resources and promote the next waiting process.
    """

    VALID_TYPES: Set[str] = {"BLOCK", "CHARACTER"}

    def __init__(self) -> None:
        self.resources: Dict[str, Resource] = {}
        self.process_holdings: Dict[str, Set[str]] = defaultdict(set)
        self.waiting_queues: Dict[str, deque] = defaultdict(deque)
        self.graph = ResourceAllocationGraph()

    # ------------------------------------------------------------------
    # Resource registration
    # ------------------------------------------------------------------

    def add_resource(self, resource_id: str, resource_type: str) -> None:
        """
        Registers a new I/O device.

        Each device has exactly one instance and is nonpreemptable,
        satisfying the mutual-exclusion and no-preemption deadlock conditions.
        """
        resource_type = resource_type.upper()

        if resource_type not in self.VALID_TYPES:
            print(f"[ERROR] Unknown type '{resource_type}'. Use BLOCK or CHARACTER.")
            return

        if resource_id in self.resources:
            print(f"[WARNING] Resource '{resource_id}' is already registered.")
            return

        self.resources[resource_id] = Resource(
            resource_id=resource_id,
            resource_type=resource_type,
        )

        # Ensure the resource node exists in the graph from the start.
        self.graph.add_node(self.graph.resource_node(resource_id))

        print(f"[RESOURCE ADDED] {resource_id} ({resource_type} device)")

    # ------------------------------------------------------------------
    # Request handling
    # ------------------------------------------------------------------

    def request_resource(self, process_id: str, resource_id: str) -> None:
        """
        Handles a process request for a resource.

        Three cases:
            1. The process already holds this resource — no-op with info.
            2. The resource is free — allocate immediately (R→P edge added).
            3. The resource is busy — block the process (P→R edge added)
               and run deadlock detection.

        The hold-and-wait deadlock condition arises naturally: a process may
        hold one resource while being blocked waiting for another.
        """
        print(f"\n[REQUEST] Process {process_id} requests Resource {resource_id}")

        if resource_id not in self.resources:
            print(f"[ERROR] Resource '{resource_id}' does not exist.")
            return

        resource = self.resources[resource_id]
        process_node = self.graph.process_node(process_id)
        resource_node = self.graph.resource_node(resource_id)

        # Ensure both nodes exist in the graph.
        self.graph.add_node(process_node)
        self.graph.add_node(resource_node)

        # Case 1: already held by this process.
        if resource.held_by == process_id:
            print(f"[INFO] Process {process_id} already holds Resource {resource_id}.")
            return

        # Case 2: resource is free — grant immediately.
        if resource.held_by is None:
            self._allocate(process_id, resource_id)
            print(f"[GRANTED] Resource {resource_id} allocated to Process {process_id}.")
            return

        # Case 3: resource is busy — block the requesting process.
        current_holder = resource.held_by

        # Add to waiting queue only if not already queued.
        if process_id not in self.waiting_queues[resource_id]:
            self.waiting_queues[resource_id].append(process_id)

        # Add P→R (waiting) edge to the RAG.
        self.graph.add_edge(process_node, resource_node)

        print(
            f"[BLOCKED] Resource {resource_id} is held by Process {current_holder}. "
            f"Process {process_id} is now waiting."
        )

        # Specification requirement: run detection after every blocked request.
        self.run_deadlock_detection()

    # ------------------------------------------------------------------
    # Release handling
    # ------------------------------------------------------------------

    def release_resource(self, process_id: str, resource_id: str) -> None:
        """
        Releases a resource held by a process.

        The R→P (allocation) edge is removed.
        The waiting queue is then checked; the next process receives the
        resource and its P→R (waiting) edge is replaced with R→P.
        """
        print(f"\n[RELEASE] Process {process_id} releases Resource {resource_id}")

        if resource_id not in self.resources:
            print(f"[ERROR] Resource '{resource_id}' does not exist.")
            return

        resource = self.resources[resource_id]

        if resource.held_by != process_id:
            print(f"[ERROR] Process {process_id} does not hold Resource {resource_id}.")
            return

        # Free the resource.
        resource.held_by = None
        self.process_holdings[process_id].discard(resource_id)

        # Remove R→P (allocation) edge.
        self.graph.remove_edge(
            self.graph.resource_node(resource_id),
            self.graph.process_node(process_id),
        )

        print(f"[RELEASED] Resource {resource_id} released by Process {process_id}.")

        # Promote the next waiting process, if any.
        self._grant_to_next_waiter(resource_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _allocate(self, process_id: str, resource_id: str) -> None:
        """
        Unconditionally grants a free resource to a process.

        Removes any existing P→R (waiting) edge and adds an R→P
        (allocation) edge.
        """
        resource = self.resources[resource_id]
        resource.held_by = process_id
        self.process_holdings[process_id].add(resource_id)

        process_node = self.graph.process_node(process_id)
        resource_node = self.graph.resource_node(resource_id)

        # Remove waiting edge if the process was previously blocked.
        self.graph.remove_edge(process_node, resource_node)

        # Add allocation edge: R → P.
        self.graph.add_edge(resource_node, process_node)

    def _grant_to_next_waiter(self, resource_id: str) -> None:
        """
        Promotes the first process in the waiting queue to hold the resource.

        Each dequeued process has its P→R (waiting) edge removed.
        If the resource is still free (it always should be at this point),
        the process is allocated the resource via _allocate().
        If an unexpected state is detected, the process is re-queued at the
        front and the waiting edge is restored to preserve graph consistency.
        """
        queue = self.waiting_queues[resource_id]

        while queue:
            next_process = queue.popleft()

            process_node = self.graph.process_node(next_process)
            resource_node = self.graph.resource_node(resource_id)

            # Optimistically remove the waiting edge.
            self.graph.remove_edge(process_node, resource_node)

            if self.resources[resource_id].held_by is None:
                # Resource is free — grant it.
                self._allocate(next_process, resource_id)
                print(
                    f"[AUTO-GRANTED] Resource {resource_id} "
                    f"granted to waiting Process {next_process}."
                )
                return
            else:
                # Defensive: resource was somehow re-acquired between the
                # release and this grant.  Restore the waiting edge and
                # put the process back at the front of the queue.
                self.graph.add_edge(process_node, resource_node)
                queue.appendleft(next_process)
                return

    # ------------------------------------------------------------------
    # Deadlock detection
    # ------------------------------------------------------------------

    def run_deadlock_detection(self) -> None:
        """
        Runs cycle detection on the current RAG and reports the result.
        """
        print("[DEADLOCK CHECK] Analysing Resource Allocation Graph...")

        has_deadlock, cycle = self.graph.detect_cycle()

        if has_deadlock:
            deadlocked = self._processes_in_cycle(cycle)
            print("[*** DEADLOCK DETECTED ***] Circular wait found.")
            print(f"[CYCLE]               {self._format_cycle(cycle)}")
            print(f"[DEADLOCKED PROCESSES] {', '.join(deadlocked)}")
        else:
            print("[NO DEADLOCK] No cycle found in the Resource Allocation Graph.")

    # ------------------------------------------------------------------
    # Status display
    # ------------------------------------------------------------------

    def print_status(self) -> None:
        """Prints the full current system state."""
        print("\n==================== SYSTEM STATUS ====================")

        # Resources table
        print("\nResources:")
        if not self.resources:
            print("  (none)")
        else:
            for rid in sorted(self.resources):
                res = self.resources[rid]
                holder = res.held_by if res.held_by else "Free"
                print(
                    f"  {rid:<14} Type: {res.resource_type:<10}  Holder: {holder}"
                )

        # Process holdings
        print("\nProcess Holdings:")
        any_holdings = any(
            h for h in self.process_holdings.values() if h
        )
        if not any_holdings:
            print("  (no process currently holds any resource)")
        else:
            for pid in sorted(self.process_holdings):
                holdings = self.process_holdings[pid]
                if holdings:
                    print(f"  Process {pid}: {', '.join(sorted(holdings))}")

        # Waiting queues
        print("\nWaiting Queues:")
        any_waiting = any(
            q for q in self.waiting_queues.values() if q
        )
        if not any_waiting:
            print("  (no processes are waiting)")
        else:
            for rid in sorted(self.waiting_queues):
                queue = self.waiting_queues[rid]
                if queue:
                    print(f"  Resource {rid}: {' -> '.join(queue)}")

        # RAG edges
        print("\nResource Allocation Graph Edges:")
        any_edges = any(
            edges for edges in self.graph.adjacency.values() if edges
        )
        if not any_edges:
            print("  (no edges)")
        else:
            for from_node in sorted(self.graph.adjacency):
                for to_node in sorted(self.graph.adjacency[from_node]):
                    print(
                        f"  {self.graph.pretty_node(from_node):<22}"
                        f"  ->  {self.graph.pretty_node(to_node)}"
                    )

        print("=======================================================\n")

    # ------------------------------------------------------------------
    # Formatting helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_cycle(cycle: List[str]) -> str:
        return " -> ".join(
            ResourceAllocationGraph.pretty_node(n) for n in cycle
        )

    @staticmethod
    def _processes_in_cycle(cycle: List[str]) -> List[str]:
        """Returns unique process IDs found in a cycle, in order of appearance."""
        seen: Set[str] = set()
        result: List[str] = []
        for node in cycle:
            if node.startswith("P:"):
                pid = node[2:]
                if pid not in seen:
                    seen.add(pid)
                    result.append(pid)
        return result


# ---------------------------------------------------------------------------
# Command Processor
# ---------------------------------------------------------------------------

class CommandProcessor:
    """
    Parses text commands and dispatches them to the IOResourceManager.

    Supported commands:
        RESOURCE <id> <BLOCK|CHARACTER>
        REQUEST  <process_id> <resource_id>
        RELEASE  <process_id> <resource_id>
        STATUS
        DETECT
        HELP
        EXIT
    """

    def __init__(self) -> None:
        self.manager = IOResourceManager()

    def execute(self, line: str) -> None:
        """
        Parses and executes a single command line.
        Blank lines and lines starting with # are silently skipped.
        """
        line = line.strip()

        if not line or line.startswith("#"):
            return

        parts = line.split()
        command = parts[0].upper()

        dispatch = {
            "RESOURCE": self._cmd_resource,
            "REQUEST":  self._cmd_request,
            "RELEASE":  self._cmd_release,
            "STATUS":   lambda _: self.manager.print_status(),
            "DETECT":   lambda _: self.manager.run_deadlock_detection(),
            "HELP":     lambda _: self._print_help(),
            "EXIT":     lambda _: self._exit(),
        }

        handler = dispatch.get(command)

        if handler is None:
            print(f"[ERROR] Unknown command '{command}'. Type HELP for options.")
            return

        handler(parts)

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    def _cmd_resource(self, parts: List[str]) -> None:
        if len(parts) != 3:
            print("[ERROR] Usage: RESOURCE <resource_id> <BLOCK|CHARACTER>")
            return
        self.manager.add_resource(parts[1], parts[2])

    def _cmd_request(self, parts: List[str]) -> None:
        if len(parts) != 3:
            print("[ERROR] Usage: REQUEST <process_id> <resource_id>")
            return
        self.manager.request_resource(parts[1], parts[2])

    def _cmd_release(self, parts: List[str]) -> None:
        if len(parts) != 3:
            print("[ERROR] Usage: RELEASE <process_id> <resource_id>")
            return
        self.manager.release_resource(parts[1], parts[2])

    @staticmethod
    def _exit() -> None:
        print("Exiting simulator.")
        sys.exit(0)

    @staticmethod
    def _print_help() -> None:
        print("""
Available Commands
------------------
RESOURCE <resource_id> <BLOCK|CHARACTER>
    Register a new I/O device.
    Example: RESOURCE BluRay BLOCK
             RESOURCE Scanner CHARACTER

REQUEST <process_id> <resource_id>
    Request a resource for a process. Blocks if the resource is busy.
    Example: REQUEST P1 Scanner

RELEASE <process_id> <resource_id>
    Release a resource held by a process.
    Example: RELEASE P1 Scanner

STATUS
    Display all resources, process holdings, waiting queues, and RAG edges.

DETECT
    Manually trigger deadlock detection.

HELP
    Show this command reference.

EXIT
    Quit interactive mode.
""")


# ---------------------------------------------------------------------------
# Entry Points
# ---------------------------------------------------------------------------

def _load_default_resources(processor: CommandProcessor) -> None:
    """
    Loads a default set of block and character devices for interactive testing.
    Covers the device types specified in the assignment brief.
    """
    defaults = [
        ("BluRay",  "BLOCK"),
        ("USB",     "BLOCK"),
        ("Printer", "CHARACTER"),
        ("Scanner", "CHARACTER"),
    ]
    for resource_id, resource_type in defaults:
        processor.manager.add_resource(resource_id, resource_type)


def run_from_file(file_path: str) -> None:
    """Reads and executes simulator commands from a text file."""
    processor = CommandProcessor()

    print("I/O Resource Manager and Deadlock Detection Simulator")
    print(f"Loading commands from: {file_path}\n")

    try:
        with open(file_path, "r", encoding="utf-8") as fh:
            for line_num, line in enumerate(fh, start=1):
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    print(f"\n--- Line {line_num}: {stripped} ---")
                processor.execute(line)

    except FileNotFoundError:
        print(f"[ERROR] File not found: '{file_path}'")
        sys.exit(1)
    except OSError as exc:
        print(f"[ERROR] Cannot read '{file_path}': {exc}")
        sys.exit(1)


def run_interactive() -> None:
    """Starts the interactive command-line mode."""
    processor = CommandProcessor()

    print("I/O Resource Manager and Deadlock Detection Simulator")
    print("Interactive mode — default devices loaded.\n")

    _load_default_resources(processor)

    print("\nType HELP for a command reference. Type EXIT to quit.\n")

    while True:
        try:
            processor.execute(input("sim> "))
        except (KeyboardInterrupt, EOFError):
            print("\nExiting simulator.")
            break


def main() -> None:
    """Program entry point."""
    if len(sys.argv) == 1:
        run_interactive()
    elif len(sys.argv) == 2:
        run_from_file(sys.argv[1])
    else:
        print("Usage:")
        print("  python io_deadlock_simulator.py")
        print("  python io_deadlock_simulator.py input.txt")
        sys.exit(1)


if __name__ == "__main__":
    main()
