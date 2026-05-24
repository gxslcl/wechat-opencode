"""Sequential execution queue with timeout handling."""

import logging
import queue
import threading
from typing import Callable, Optional

from wechat_opencode.config import Config
from wechat_opencode.session import OpenCodeSession
from wechat_opencode.types import Command, ExecutionResult

logger = logging.getLogger(__name__)


class ExecutionQueue:
    """Sequential command queue — one command at a time."""

    def __init__(
        self,
        session: OpenCodeSession,
        config: Config,
        on_result: Callable[[Command, ExecutionResult], None],
        on_queued: Optional[Callable[[Command, int], None]] = None,
    ) -> None:
        self._session = session
        self._config = config
        self._on_result = on_result
        self._on_queued = on_queued
        self._queue: queue.Queue[Optional[Command]] = queue.Queue()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._current_command: Optional[Command] = None

    def start(self) -> None:
        """Start the queue processor thread."""
        self._running = True
        self._thread = threading.Thread(target=self._processor, daemon=True)
        self._thread.start()
        logger.info("ExecutionQueue started")

    def stop(self) -> None:
        """Signal the processor to stop and wait for current command."""
        self._running = False
        self._queue.put(None)  # sentinel to unblock the queue.get()
        if self._thread is not None:
            self._thread.join(timeout=10)
        logger.info("ExecutionQueue stopped")

    def submit(self, command: Command) -> None:
        """Add a command to the queue."""
        q_size = self._queue.qsize()
        if q_size > 0 and self._on_queued:
            self._on_queued(command, q_size)
        self._queue.put(command)
        logger.info("Command queued: %s (queue size: %d)", command.content[:50], q_size + 1)

    @property
    def is_busy(self) -> bool:
        """Whether a command is currently being executed."""
        return self._current_command is not None

    @property
    def pending_count(self) -> int:
        """Number of commands waiting in the queue (excluding current)."""
        return self._queue.qsize()

    def _processor(self) -> None:
        """Background thread that processes commands sequentially."""
        while self._running:
            try:
                command = self._queue.get(timeout=1)
            except queue.Empty:
                continue

            if command is None:
                break

            self._current_command = command
            try:
                logger.info("Executing: %s", command.content[:80])
                result = self._session.execute_with_timeout(
                    command.content,
                    timeout=self._config.opencode.command_timeout,
                    session_id=command.session_id,
                )
                try:
                    self._on_result(command, result)
                except Exception as e:
                    logger.error("Error in on_result callback: %s", e)
            except Exception as e:
                logger.error("Execution failed: %s", e)
                error_result = ExecutionResult(
                    success=False, output="", error=str(e),
                )
                try:
                    self._on_result(command, error_result)
                except Exception:
                    pass
            finally:
                self._current_command = None
                self._queue.task_done()
