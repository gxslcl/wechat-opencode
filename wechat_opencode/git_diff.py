"""Git diff helper — detect file changes after opencode execution."""

import logging
import subprocess
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class GitDiff:
    """Wraps git diff to detect file changes after opencode operations.

    Used after each command execution to show the user what changed.
    """

    def __init__(self, project_dir: str = ".") -> None:
        self._project_dir = project_dir

    def check_available(self) -> bool:
        """Check if git is available in the project directory."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                cwd=self._project_dir,
                capture_output=True, text=True, timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False

    def get_stat(self) -> Optional[str]:
        """Get the git diff stat (summary of changes).
        
        Returns ``None`` if git is not available or there are no changes.
        """
        if not self.check_available():
            return None
        try:
            result = subprocess.run(
                ["git", "diff", "--stat", "--no-color"],
                cwd=self._project_dir,
                capture_output=True, text=True, timeout=10,
            )
            out = result.stdout.strip()
            return out if out else None
        except Exception as e:
            logger.debug("Git diff stat failed: %s", e)
            return None

    def get_diff(self, max_lines: int = 80, max_size: int = 4000) -> Optional[str]:
        """Get the full git diff, truncated for messaging.

        Returns ``None`` if git is not available or there are no changes.
        """
        if not self.check_available():
            return None
        try:
            result = subprocess.run(
                ["git", "diff", "--no-color", "-U3"],
                cwd=self._project_dir,
                capture_output=True, text=True, timeout=10,
            )
            out = result.stdout.strip()
            if not out:
                return None

            # Truncate to message-friendly size
            if len(out) > max_size:
                out = out[:max_size] + "\n... (输出过长，已截断)"
            return out
        except Exception as e:
            logger.debug("Git diff failed: %s", e)
            return None

    def get_changed_files(self) -> list:
        """Return list of changed file paths."""
        if not self.check_available():
            return []
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only"],
                cwd=self._project_dir,
                capture_output=True, text=True, timeout=10,
            )
            return [f for f in result.stdout.strip().split("\n") if f]
        except Exception:
            return []

    def has_changes(self) -> bool:
        """Check if the working tree has any changes."""
        return len(self.get_changed_files()) > 0
