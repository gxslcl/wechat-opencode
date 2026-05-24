"""Graceful shutdown and signal handling."""

import logging
import signal
import threading
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class ShutdownHandler:
    """Registers OS signal handlers and provides a shutdown event."""

    def __init__(self) -> None:
        self._shutdown_event = threading.Event()
        self._on_shutdown: Optional[Callable[[], None]] = None

    @property
    def is_shutting_down(self) -> bool:
        return self._shutdown_event.is_set()

    @property
    def shutdown_event(self) -> threading.Event:
        return self._shutdown_event

    def register(self, on_shutdown: Callable[[], None]) -> None:
        """Register the shutdown callback and signal handlers."""
        self._on_shutdown = on_shutdown
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)
        logger.info("Shutdown handler registered (SIGINT, SIGTERM)")

    def trigger_shutdown(self) -> None:
        """Programmatically trigger a graceful shutdown."""
        logger.info("Shutdown triggered programmatically")
        self._shutdown_event.set()
        if self._on_shutdown:
            self._on_shutdown()

    def _handle_signal(self, signum: int, frame) -> None:
        """Signal handler — sets the shutdown event and invokes callback."""
        sig_name = signal.Signals(signum).name
        logger.info("Received signal %s, initiating shutdown...", sig_name)
        self._shutdown_event.set()
        if self._on_shutdown:
            self._on_shutdown()
