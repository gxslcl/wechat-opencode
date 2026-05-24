"""Tests for wechat_opencode.queue."""

import threading
import time
from unittest.mock import MagicMock

import pytest

from wechat_opencode.config import Config
from wechat_opencode.queue import ExecutionQueue
from wechat_opencode.types import Command, ExecutionResult, WxMessage


@pytest.fixture
def config():
    return Config()


@pytest.fixture
def results():
    return []


@pytest.fixture
def queued_notifications():
    return []


@pytest.fixture
def mock_session():
    session = MagicMock()
    session.execute_with_timeout.return_value = ExecutionResult(
        success=True, output="done", duration_seconds=1.0,
    )
    return session


@pytest.fixture
def queue(mock_session, config, results, queued_notifications):
    return ExecutionQueue(
        session=mock_session,
        config=config,
        on_result=lambda cmd, res: results.append((cmd, res)),
        on_queued=lambda cmd, pos: queued_notifications.append((cmd, pos)),
    )


def _make_command(content: str) -> Command:
    msg = WxMessage(
        id="1", type=1, sender="filehelper",
        roomid="", content=f"/oc {content}", timestamp=1700000000,
    )
    return Command(original_message=msg, content=content, timestamp=1700000000)


class TestExecutionQueue:
    def test_sequential_execution(self, queue, results, mock_session):
        queue.start()
        try:
            cmd1 = _make_command("first")
            cmd2 = _make_command("second")
            queue.submit(cmd1)
            queue.submit(cmd2)
            time.sleep(0.5)  # allow processing
            assert len(results) == 2
        finally:
            queue.stop()

    def test_queued_notification(self, queue, results, queued_notifications, mock_session):
        # Make execution slow so second command queues
        mock_session.execute_with_timeout.side_effect = lambda cmd, timeout: (
            time.sleep(0.3),
            ExecutionResult(success=True, output="done", duration_seconds=0.3),
        )[1]

        queue.start()
        try:
            cmd1 = _make_command("slow")
            cmd2 = _make_command("queued")
            queue.submit(cmd1)
            queue.submit(cmd2)
            time.sleep(1.0)
            assert len(queued_notifications) >= 1
        finally:
            queue.stop()

    def test_error_doesnt_block_queue(self, queue, results, mock_session):
        mock_session.execute_with_timeout.side_effect = [
            RuntimeError("boom"),
            ExecutionResult(success=True, output="recovered", duration_seconds=1.0),
        ]

        queue.start()
        try:
            cmd1 = _make_command("fail")
            cmd2 = _make_command("succeed")
            queue.submit(cmd1)
            queue.submit(cmd2)
            time.sleep(0.5)
            assert len(results) == 2
            assert results[0][1].success is False
            assert results[1][1].success is True
        finally:
            queue.stop()

    def test_stop_drains_current(self, queue, results, mock_session):
        mock_session.execute_with_timeout.side_effect = lambda cmd, timeout: (
            time.sleep(0.5),
            ExecutionResult(success=True, output="done", duration_seconds=0.5),
        )[1]

        queue.start()
        cmd = _make_command("long")
        queue.submit(cmd)
        time.sleep(0.1)
        queue.stop()
        # The command in flight should complete
