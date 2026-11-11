"""Swarm multi-agent system — Task persistence and DAG algorithms.

Each task is stored independently as tasks/task-{id}.json with full CRUD support.
Provides DAG algorithms: dependency resolution, cycle detection, and topological layering.
"""

from __future__ import annotations

import threading
import os
import time
import uuid
from collections import Counter, defaultdict, deque
from pathlib import Path

from src.swarm.models import SwarmAgentSpec, SwarmTask, TaskStatus


def _read_task(path: Path) -> SwarmTask:
    from src.swarm.store import _REPLACE_ATTEMPTS, _REPLACE_BACKOFF, _is_transient_windows_error

    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            return SwarmTask.model_validate_json(path.read_text(encoding="utf-8"))
        except OSError as exc:
            # Python's open() can report errno 13 without winerror during a Windows rename.
            transient = _is_transient_windows_error(exc) or (
                os.name == "nt" and isinstance(exc, PermissionError) and getattr(exc, "winerror", None) is None
            )
            if not transient or attempt == _REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(_REPLACE_BACKOFF[attempt])


class TaskStore:
    """File-based persistence layer for tasks.

    Each task is stored at run_dir/tasks/task-{id}.json.

    Attributes:
        run_dir: Root directory of the current run.
    """

    def __init__(self, run_dir: Path) -> None:
        """Initialize TaskStore.

        Args:
            run_dir: Path to .swarm/runs/{run_id}/ directory.
        """
        self.run_dir = run_dir
        self._tasks_dir = run_dir / "tasks"
        self._tasks_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _task_path(self, task_id: str) -> Path:
        """Return the file path for a task.

        Args:
            task_id: Task ID.

        Returns:
            Path to the task JSON file.
        """
        return self._tasks_dir / f"task-{task_id}.json"

    def save_task(self, task: SwarmTask) -> None:
        """Save or overwrite task state.

        Args:
            task: SwarmTask instance.
        """
        from src.swarm.store import _replace_with_retry

        path = self._task_path(task.id)
        # self._lock is per instance, and resolve_dependencies() writes the same
        # files without it; a shared ".tmp" name let one writer's rename consume
        # another's unwritten temp file (#1536).
        tmp_path = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        with self._lock:
            tmp_path.write_text(task.model_dump_json(indent=2), encoding="utf-8")
            _replace_with_retry(tmp_path, path)

    def load_task(self, task_id: str) -> SwarmTask:
        """Load a task by ID.

        Args:
            task_id: Task ID.

        Returns:
            SwarmTask instance.

        Raises:
            FileNotFoundError: If the task file does not exist.
        """
        path = self._task_path(task_id)
        if not path.exists():
            raise FileNotFoundError(f"Task not found: {path.name}")
        return _read_task(path)

    def load_all(self) -> list[SwarmTask]:
        """Load all tasks for the current run.

        Returns:
            List of SwarmTask sorted by ID.
        """
        tasks: list[SwarmTask] = []
        for path in sorted(self._tasks_dir.glob("task-*.json")):
            tasks.append(
                _read_task(path)
            )
        return tasks

    def update_status(
        self, task_id: str, status: TaskStatus, **kwargs: str | int | list[str] | None
    ) -> SwarmTask:
        """Update task status and additional fields.

        Args:
            task_id: Task ID.
            status: New status.
            **kwargs: Optional fields such as summary, error, completed_at, artifacts, etc.

        Returns:
            Updated SwarmTask instance.
        """
        task = self.load_task(task_id)
        updated_data = task.model_dump()
        updated_data["status"] = status
        for key, value in kwargs.items():
            if key in updated_data:
                updated_data[key] = value
        updated_task = SwarmTask.model_validate(updated_data)
        self.save_task(updated_task)
        return updated_task


def resolve_dependencies(tasks_dir: Path, completed_task_id: str) -> list[str]:
    """Remove a completed task ID from blocked_by in all downstream tasks.

    Scans all task files under tasks_dir and removes completed_task_id from each
    task's blocked_by list. If a task's blocked_by becomes empty and its status
    is blocked, it is marked as newly unblocked (pending).

    Args:
        tasks_dir: Path to the tasks/ directory.
        completed_task_id: ID of the just-completed task.

    Returns:
        List of newly unblocked task IDs (blocked_by went from non-empty to empty).
    """
    from src.swarm.store import _replace_with_retry

    newly_unblocked: list[str] = []

    for path in tasks_dir.glob("task-*.json"):
        task = _read_task(path)
        if completed_task_id not in task.blocked_by:
            continue

        new_blocked_by = [tid for tid in task.blocked_by if tid != completed_task_id]
        updated_data = task.model_dump()
        updated_data["blocked_by"] = new_blocked_by

        if not new_blocked_by and task.status == TaskStatus.blocked:
            updated_data["status"] = TaskStatus.pending
            newly_unblocked.append(task.id)

        updated_task = SwarmTask.model_validate(updated_data)
        tmp_path = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        tmp_path.write_text(updated_task.model_dump_json(indent=2), encoding="utf-8")
        _replace_with_retry(tmp_path, path)

    return newly_unblocked


def validate_dag(
    tasks: list[SwarmTask], agents: list[SwarmAgentSpec] | None = None
) -> None:
    """Validate identities, dependency edges and upstream context references.

    Args:
        tasks: List of SwarmTask.
        agents: Agent roster, when validating a complete run rather than a graph.

    Raises:
        ValueError: If identities/references are invalid or a cycle is detected.
    """
    errors: list[str] = []
    task_counts = Counter(task.id for task in tasks)
    all_ids = set(task_counts)
    if any(not task_id.strip() for task_id in all_ids):
        errors.append("Task id must not be empty")
    for task_id, count in task_counts.items():
        if count > 1:
            errors.append(f"Duplicate task id: {task_id}")

    if agents is not None:
        agent_counts = Counter(agent.id for agent in agents)
        if any(not agent_id.strip() for agent_id in agent_counts):
            errors.append("Agent id must not be empty")
        for agent_id, count in agent_counts.items():
            if count > 1:
                errors.append(f"Duplicate agent id: {agent_id}")
        for task in tasks:
            if task.agent_id not in agent_counts:
                errors.append(
                    f"Task '{task.id}' references unknown agent '{task.agent_id}'"
                )

    for task in tasks:
        for dep in task.depends_on:
            if dep not in all_ids:
                errors.append(
                    f"Task '{task.id}' depends on unknown task '{dep}'"
                )
        for key, source in task.input_from.items():
            if source not in all_ids:
                errors.append(
                    f"Task '{task.id}' input_from '{key}' references unknown task '{source}'"
                )
    if errors:
        raise ValueError("\n".join(errors))

    graph: dict[str, list[str]] = {t.id: list(t.depends_on) for t in tasks}

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {tid: WHITE for tid in all_ids}
    path: list[str] = []
    ancestors: dict[str, set[str]] = {tid: set() for tid in all_ids}

    def dfs(node: str) -> None:
        """DFS traversal to detect back edges.

        Args:
            node: Current node ID.

        Raises:
            ValueError: If a cycle is detected.
        """
        color[node] = GRAY
        path.append(node)

        for neighbor in graph.get(node, []):
            if color[neighbor] == GRAY:
                cycle_start = path.index(neighbor)
                cycle = path[cycle_start:] + [neighbor]
                raise ValueError(
                    f"Cycle detected in task DAG: {' -> '.join(cycle)}"
                )
            if color[neighbor] == WHITE:
                dfs(neighbor)
            ancestors[node].add(neighbor)
            ancestors[node].update(ancestors[neighbor])

        path.pop()
        color[node] = BLACK

    for tid in graph:
        if color[tid] == WHITE:
            dfs(tid)

    for task in tasks:
        for key, source in task.input_from.items():
            if source not in ancestors[task.id]:
                errors.append(
                    f"Task '{task.id}' input_from '{key}' references '{source}', "
                    "which is not upstream in the DAG"
                )
    if errors:
        raise ValueError("\n".join(errors))


def topological_layers(tasks: list[SwarmTask]) -> list[list[str]]:
    """Kahn's algorithm topological layering; tasks in the same layer can run in parallel.

    Args:
        tasks: List of SwarmTask (must be a valid acyclic DAG).

    Returns:
        List of layers in execution order; each layer contains task IDs that can
        run in parallel.

    Raises:
        ValueError: If the DAG contains a cycle (topological sort cannot complete).
    """
    in_degree: dict[str, int] = {t.id: 0 for t in tasks}
    dependents: dict[str, list[str]] = defaultdict(list)

    for task in tasks:
        in_degree[task.id] = len(task.depends_on)
        for dep in task.depends_on:
            dependents[dep].append(task.id)

    queue: deque[str] = deque(
        tid for tid, deg in in_degree.items() if deg == 0
    )

    layers: list[list[str]] = []
    processed = 0

    while queue:
        layer: list[str] = list(queue)
        queue.clear()
        layers.append(layer)
        processed += len(layer)

        for tid in layer:
            for downstream in dependents[tid]:
                in_degree[downstream] -= 1
                if in_degree[downstream] == 0:
                    queue.append(downstream)

    if processed != len(tasks):
        raise ValueError(
            f"DAG contains a cycle: processed {processed}/{len(tasks)} tasks"
        )

    return layers
