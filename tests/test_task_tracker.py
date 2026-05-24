"""Tests for wechat_opencode.task_tracker."""

import json
import os
import tempfile

import pytest

from wechat_opencode.task_tracker import TaskTracker, Task, TaskStep


@pytest.fixture
def tracker(tmp_path):
    data_dir = str(tmp_path / "data")
    return TaskTracker(data_dir=data_dir)


class TestTaskTracker:
    def test_start_task(self, tracker):
        task = tracker.start_task("hello", session_id="ses_abc")
        assert task.goal == "hello"
        assert task.session_id == "ses_abc"
        assert task.status == "running"
        assert len(task.steps) == 1
        assert task.steps[0].description == "hello"

    def test_start_task_with_steps(self, tracker):
        task = tracker.start_task("build blog", steps=["step1", "step2", "step3"])
        assert len(task.steps) == 3
        assert task.steps[0].description == "step1"
        assert task.steps[0].status == "pending"

    def test_add_and_update_step(self, tracker):
        task = tracker.start_task("test")
        tracker.add_step(task.id, "extra step")
        assert len(tracker.get_by_id(task.id).steps) == 2

        tracker.update_step(task.id, 0, "done", "output text")
        t = tracker.get_by_id(task.id)
        assert t.steps[0].status == "done"
        assert t.steps[0].output == "output text"

    def test_mark_complete(self, tracker):
        task = tracker.start_task("test", steps=["a", "b"])
        tracker.update_step(task.id, 0, "running")
        tracker.mark_complete(task.id, True)
        t = tracker.get_by_id(task.id)
        assert t.status == "done"

    def test_mark_failed(self, tracker):
        task = tracker.start_task("test")
        tracker.mark_complete(task.id, False)
        t = tracker.get_by_id(task.id)
        assert t.status == "failed"

    def test_get_active(self, tracker):
        t1 = tracker.start_task("a")
        t2 = tracker.start_task("b")
        tracker.mark_complete(t1.id, True)
        active = tracker.get_active()
        assert len(active) == 1
        assert active[0].id == t2.id

    def test_list_recent(self, tracker):
        for i in range(5):
            tracker.start_task(f"task {i}")
        recent = tracker.list_recent(3)
        assert len(recent) == 3

    def test_get_recent_results(self, tracker):
        t1 = tracker.start_task("good one")
        tracker.mark_complete(t1.id, True)
        t2 = tracker.start_task("bad one")
        tracker.mark_complete(t2.id, False)
        results = tracker.get_recent_results(2)
        assert len(results) == 2
        assert "good one" in str(results)
        assert "bad one" in str(results)

    def test_persistence(self, tmp_path):
        """Tasks should survive tracker re-creation from the same file."""
        data_dir = str(tmp_path / "data")
        t1 = TaskTracker(data_dir=data_dir)
        t1.start_task("persistent task", session_id="ses_x")

        t2 = TaskTracker(data_dir=data_dir)
        tasks = t2.list_recent()
        assert len(tasks) == 1
        assert tasks[0].goal == "persistent task"
        assert tasks[0].session_id == "ses_x"

    def test_truncate_long_output(self, tracker):
        task = tracker.start_task("test")
        tracker.update_step(task.id, 0, "done", "x" * 1000)
        t = tracker.get_by_id(task.id)
        assert len(t.steps[0].output) <= 500

    def test_get_by_id_not_found(self, tracker):
        assert tracker.get_by_id("nonexistent") is None
