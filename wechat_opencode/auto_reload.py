"""Auto-reload — watch source files and restart when changes are detected."""

import logging
import os
import threading
from typing import Callable, Dict, Optional

logger = logging.getLogger(__name__)


class AutoReloader:
    """Polling-based file watcher that triggers a callback when .py files change.

    Used to enable "zero-touch" development: edit any source file →
    the service restarts automatically, picking up code changes.
    """

    def __init__(
        self,
        watch_dir: str,
        on_change: Callable[[], None],
        interval: int = 3,
        is_busy: Optional[Callable[[], bool]] = None,
    ) -> None:
        self._watch_dir = watch_dir
        self._on_change = on_change
        self._interval = interval
        self._is_busy = is_busy
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._snapshot: Dict[str, float] = {}
        self._first_check = True  # skip first check (files just loaded)
        self._deferred = False   # restart deferred due to busy worker

    def start(self) -> None:
        """Start the background watcher thread."""
        self._running = True
        self._take_snapshot()
        self._thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._thread.start()
        logger.info(
            "AutoReloader started (watching %s every %ds)",
            self._watch_dir, self._interval,
        )

    def stop(self) -> None:
        """Stop the watcher."""
        self._running = False
        logger.info("AutoReloader stopped")

    def _watch_loop(self) -> None:
        """Background loop — poll for file changes."""
        import time
        while self._running:
            time.sleep(self._interval)
            if self._check_changes():
                if self._is_busy and self._is_busy():
                    if not self._deferred:
                        logger.info(
                            "Source files changed but worker is busy — "
                            "deferring restart"
                        )
                        self._deferred = True
                    continue
                if self._deferred:
                    logger.info("Worker idle — triggering deferred restart")
                else:
                    logger.info("Source files changed — triggering restart")
                self._running = False
                self._on_change()

    def _check_changes(self) -> bool:
        """Scan .py files in the watch directory for changes.

        Returns True if any file was added, removed, or modified.
        """
        current: Dict[str, float] = {}
        changed = False

        try:
            for root, dirs, files in os.walk(self._watch_dir):
                # Skip __pycache__ and hidden dirs
                dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
                for f in files:
                    if not f.endswith(".py"):
                        continue
                    path = os.path.join(root, f).replace("\\", "/")
                    try:
                        mtime = os.path.getmtime(path)
                    except OSError:
                        continue
                    current[path] = mtime

                    if self._first_check:
                        continue

                    prev = self._snapshot.get(path)
                    if prev is None:
                        changed = True  # new file
                    elif mtime > prev:
                        changed = True  # modified
        except Exception:
            pass

        # Check for removed files
        if not self._first_check:
            for path in self._snapshot:
                if path not in current:
                    changed = True
                    break

        self._snapshot = current

        if self._first_check:
            self._first_check = False
            return False

        return changed

    def _take_snapshot(self) -> None:
        """Build initial file snapshot."""
        try:
            for root, dirs, files in os.walk(self._watch_dir):
                dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
                for f in files:
                    if not f.endswith(".py"):
                        continue
                    path = os.path.join(root, f).replace("\\", "/")
                    try:
                        self._snapshot[path] = os.path.getmtime(path)
                    except OSError:
                        continue
        except Exception:
            pass
