"""Task tracker — record and manage task progress with a JSON file."""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class TaskStep:
    index: int
    description: str
    status: str = "pending"  # pending, running, done, failed
    output: str = ""


@dataclass
class Task:
    id: str
    goal: str
    session_id: str = ""
    status: str = "running"  # running, done, failed
    created_at: float = 0.0
    updated_at: float = 0.0
    steps: List[TaskStep] = field(default_factory=list)


class TaskTracker:
    """JSON-file-backed task tracker. Thread-safe for the execution queue.

    Each task records the goal, session, and step-by-step progress.
    """

    def __init__(self, data_dir: str = "./data") -> None:
        self._data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self._file = os.path.join(data_dir, "tasks.json")
        self._tasks: List[Task] = self._load()

    # --- Public API -----------------------------------------------------------

    def start_task(self, goal: str, session_id: str = "", steps: Optional[List[str]] = None) -> Task:
        """Create a new task and record the first step (the goal itself)."""
        now = time.time()
        task = Task(
            id=f"task_{int(now * 1000)}",
            goal=goal,
            session_id=session_id,
            created_at=now,
            updated_at=now,
            steps=([TaskStep(index=0, description=s) for i, s in enumerate(steps)]
                   if steps else [TaskStep(index=0, description=goal, status="running")]),
        )
        self._tasks.append(task)
        self._save()
        logger.info("Task started: %s (%d steps)", task.goal, len(task.steps))
        return task

    def add_step(self, task_id: str, description: str) -> None:
        """Add a new step to an existing task."""
        task = self._find(task_id)
        if task is None:
            return
        step = TaskStep(index=len(task.steps), description=description)
        task.steps.append(step)
        task.updated_at = time.time()
        self._save()

    def update_step(self, task_id: str, step_index: int, status: str, output: str = "") -> None:
        """Update a specific step's status and output."""
        task = self._find(task_id)
        if task is None:
            return
        for s in task.steps:
            if s.index == step_index:
                s.status = status
                s.output = output[:500]  # Truncate long output in tracker
                break
        task.updated_at = time.time()
        self._save()

    def mark_complete(self, task_id: str, success: bool) -> None:
        """Mark the entire task as done or failed."""
        task = self._find(task_id)
        if task is None:
            return
        task.status = "done" if success else "failed"
        task.updated_at = time.time()

        # Mark the current step as done/failed too
        for s in task.steps:
            if s.status == "running":
                s.status = "done" if success else "failed"
                break

        self._save()
        logger.info("Task %s marked %s", task.goal, task.status)

    def get_active(self) -> List[Task]:
        """Return tasks that are still running."""
        return [t for t in self._tasks if t.status == "running"]

    def get_by_id(self, task_id: str) -> Optional[Task]:
        """Return a task by ID, or None."""
        return self._find(task_id)

    def list_recent(self, n: int = 20) -> List[Task]:
        """Return the most recent tasks (including completed)."""
        return sorted(self._tasks, key=lambda t: t.updated_at, reverse=True)[:n]

    def clear_all(self) -> int:
        """Clear all tasks. Returns count of tasks removed."""
        count = len(self._tasks)
        self._tasks = []
        self._save()
        logger.info("Cleared %d tasks", count)
        return count

    def get_recent_results(self, n: int = 5) -> List[str]:
        """Return summary strings of the most recent task results."""
        summaries = []
        for t in self.list_recent(n):
            tag = "✅" if t.status == "done" else "❌"
            summaries.append(f"{tag} {t.goal[:80]}")
        return summaries

    # --- Internal -------------------------------------------------------------

    def _load(self) -> List[Task]:
        try:
            with open(self._file, "r", encoding="utf-8") as f:
                raw = json.load(f)
            tasks = []
            for t in raw:
                steps = [TaskStep(**s) for s in t.pop("steps", [])]
                tasks.append(Task(steps=steps, **t))
            return tasks
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _save(self) -> None:
        with open(self._file, "w", encoding="utf-8") as f:
            json.dump(
                [self._task_to_dict(t) for t in self._tasks],
                f, ensure_ascii=False, indent=2,
            )

    def _find(self, task_id: str) -> Optional[Task]:
        for t in self._tasks:
            if t.id == task_id:
                return t
        return None

    @staticmethod
    def _task_to_dict(t: Task) -> dict:
        return {
            "id": t.id,
            "goal": t.goal,
            "session_id": t.session_id,
            "status": t.status,
            "created_at": t.created_at,
            "updated_at": t.updated_at,
            "steps": [
                {"index": s.index, "description": s.description,
                 "status": s.status, "output": s.output}
                for s in t.steps
            ],
        }
