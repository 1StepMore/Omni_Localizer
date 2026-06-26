"""Background task tracking for async MCP tool calls.

Uses in-memory dict behind an abstract interface. Thread-safe via Lock.
"""
from __future__ import annotations

import threading
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum

__all__ = [
    "TaskStatus",
    "ActiveTask",
    "TaskTracker",
    "InMemoryTaskTracker",
]


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ActiveTask:
    """Represents a single async translation task."""

    def __init__(self, request_id: str, total_steps: int = 1) -> None:
        self.request_id = request_id
        self.status = TaskStatus.PENDING
        self.progress = 0.0  # 0.0 to 1.0
        self.total_steps = total_steps
        self.current_step = 0
        self.result: dict | None = None
        self.error: dict | None = None
        self.created_at = datetime.now(timezone.utc)
        self.updated_at = self.created_at


class TaskTracker(ABC):
    """Abstract interface for task tracking. Default impl is in-memory."""

    @abstractmethod
    def create_task(self, request_id: str | None = None, total_steps: int = 1) -> str:
        ...

    @abstractmethod
    def update_progress(
        self,
        request_id: str,
        status: TaskStatus,
        progress: float | None = None,
        result: dict | None = None,
        error: dict | None = None,
    ) -> None:
        ...

    @abstractmethod
    def get_task(self, request_id: str) -> ActiveTask | None:
        ...

    @abstractmethod
    def list_tasks(self) -> list[ActiveTask]:
        ...


class InMemoryTaskTracker(TaskTracker):
    """Thread-safe in-memory task tracker for single-process stdio MCP."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tasks: dict[str, ActiveTask] = {}

    def create_task(self, request_id: str | None = None, total_steps: int = 1) -> str:
        task_id = request_id or str(uuid.uuid4())
        task = ActiveTask(task_id, total_steps)
        with self._lock:
            self._tasks[task_id] = task
        return task_id

    def update_progress(
        self,
        request_id: str,
        status: TaskStatus,
        progress: float | None = None,
        result: dict | None = None,
        error: dict | None = None,
    ) -> None:
        with self._lock:
            task = self._tasks.get(request_id)
            if task is None:
                return
            task.status = status
            task.updated_at = datetime.now(timezone.utc)
            if progress is not None:
                task.progress = progress
            if result is not None:
                task.result = result
            if error is not None:
                task.error = error

    def get_task(self, request_id: str) -> ActiveTask | None:
        with self._lock:
            return self._tasks.get(request_id)

    def list_tasks(self) -> list[ActiveTask]:
        with self._lock:
            return list(self._tasks.values())
