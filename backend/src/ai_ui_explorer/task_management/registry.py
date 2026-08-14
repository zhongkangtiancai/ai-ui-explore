"""Thread-safe, in-memory registry for managed exploration tasks."""

from threading import RLock

from ai_ui_explorer.task_management.models import ManagedTask, TaskSummary


class ExplorationTaskRegistry:
    """Keep task handles only for the lifetime of the current process."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._tasks: dict[str, ManagedTask] = {}

    def create(self, entry: ManagedTask) -> ManagedTask:
        """Register one managed task and return its original handle."""
        with self._lock:
            if entry.task_id in self._tasks:
                raise ValueError("task ID is already registered")
            self._tasks[entry.task_id] = entry
            return entry

    def get(self, task_id: str) -> ManagedTask | None:
        """Return an in-process task handle when it is still registered."""
        with self._lock:
            return self._tasks.get(task_id)

    def list_summaries(self) -> list[TaskSummary]:
        """Return copied public summaries in stable public-ID order."""
        with self._lock:
            return [
                self._tasks[task_id].summary()
                for task_id in sorted(self._tasks)
            ]

    def remove_runtime(self, task_id: str) -> None:
        """Release private runtime resources without deleting task metadata."""
        with self._lock:
            task = self._tasks.get(task_id)
        if task is not None:
            task.remove_runtime()
