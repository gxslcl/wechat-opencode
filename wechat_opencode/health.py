"""Health monitor with auto-recovery for WeChat and opencode components."""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from wechat_opencode.bridge import WeChatBridge
from wechat_opencode.config import Config
from wechat_opencode.session import OpenCodeSession

logger = logging.getLogger(__name__)


@dataclass
class ComponentStatus:
    """Health status snapshot of a single component."""
    name: str
    running: bool = True  # optimistic until first check
    last_check: float = 0.0
    last_ok: float = 0.0
    failures: int = 0


class HealthMonitor:
    """Periodically checks WeChat and opencode serve health, with optional auto-recovery.

    Runs a background daemon thread at ``config.service.heartbeat_interval``
    seconds.  When ``auto_restart`` is enabled it will attempt to restart
    unhealthy components and notify the user via the *on_notify* callback.
    """

    def __init__(
        self,
        config: Config,
        bridge: WeChatBridge,
        session: OpenCodeSession,
        shutdown_event: threading.Event,
        on_notify: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._config = config
        self._bridge = bridge
        self._session = session
        self._shutdown_event = shutdown_event
        self._on_notify = on_notify
        self._interval = config.service.heartbeat_interval
        self._auto_restart = config.service.auto_restart

        self._wechat_status = ComponentStatus(name="WeChat")
        self._opencode_status = ComponentStatus(name="OpenCode")
        self._running = False
        self._thread: Optional[threading.Thread] = None

    # --- Lifecycle -----------------------------------------------------------

    def start(self) -> None:
        """Start the background health monitor thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        logger.info(
            "HealthMonitor started (interval=%ds, auto_restart=%s)",
            self._interval, self._auto_restart,
        )

    def stop(self) -> None:
        """Stop the health monitor thread."""
        self._running = False
        logger.info("HealthMonitor stopped")

    # --- Public query helpers ------------------------------------------------

    @property
    def is_healthy(self) -> bool:
        """Whether all monitored components are currently considered healthy."""
        return self._wechat_status.running and self._opencode_status.running

    def get_status(self) -> dict:
        """Return a snapshot of all component health statuses."""
        return {
            "wechat": {
                "running": self._wechat_status.running,
                "failures": self._wechat_status.failures,
                "last_ok": self._wechat_status.last_ok,
            },
            "opencode": {
                "running": self._opencode_status.running,
                "failures": self._opencode_status.failures,
                "last_ok": self._opencode_status.last_ok,
            },
            "healthy": self.is_healthy,
        }

    # --- Internal ------------------------------------------------------------

    def _monitor_loop(self) -> None:
        """Background loop — perform periodic health checks."""
        while self._running and not self._shutdown_event.is_set():
            self._check_wechat()
            self._check_opencode()

            if not self.is_healthy:
                logger.warning(
                    "Health: WeChat=%s, OpenCode=%s",
                    "UP" if self._wechat_status.running else "DOWN",
                    "UP" if self._opencode_status.running else "DOWN",
                )

            self._shutdown_event.wait(self._interval)

    def _check_wechat(self) -> None:
        """Check WeChat process and attempt recovery if needed."""
        now = time.monotonic()
        self._wechat_status.last_check = now

        try:
            running = self._bridge.is_wechat_running()
        except Exception as e:
            logger.error("Health check error (WeChat): %s", e)
            running = False

        self._update_status(self._wechat_status, running, now)

        if not running and self._auto_restart:
            self._recover_wechat()

    def _check_opencode(self) -> None:
        """Check opencode serve process and attempt recovery if needed."""
        now = time.monotonic()
        self._opencode_status.last_check = now

        try:
            running = self._session.is_serve_running()
        except Exception as e:
            logger.error("Health check error (OpenCode): %s", e)
            running = False

        self._update_status(self._opencode_status, running, now)

        if not running and self._auto_restart:
            self._recover_opencode()

    @staticmethod
    def _update_status(status: ComponentStatus, running: bool, now: float) -> None:
        """Update a component status based on a check result."""
        if running:
            status.running = True
            status.last_ok = now
            status.failures = 0
        else:
            status.running = False
            status.failures += 1
            logger.warning(
                "%s is not running (failure #%d)", status.name, status.failures,
            )

    def _recover_wechat(self) -> None:
        """Attempt to restart the WeChat bridge."""
        try:
            logger.info("Attempting WeChat bridge recovery...")
            self._bridge.stop()
            self._bridge.start()
            self._wechat_status.running = True
            self._wechat_status.failures = 0
            self._wechat_status.last_ok = time.monotonic()
            logger.info("WeChat bridge recovered successfully")
        except Exception as e:
            logger.error("WeChat bridge recovery failed: %s", e)

    def _recover_opencode(self) -> None:
        """Attempt to restart the opencode serve process."""
        try:
            logger.info("Attempting OpenCode serve recovery...")
            self._session.stop_serve()
            self._session.start_serve()
            self._opencode_status.running = True
            self._opencode_status.failures = 0
            self._opencode_status.last_ok = time.monotonic()
            logger.info("OpenCode serve recovered successfully")
        except Exception as e:
            logger.error("OpenCode serve recovery failed: %s", e)
