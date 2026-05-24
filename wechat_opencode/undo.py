"""Checkpoint / undo — save and restore git state before opencode operations."""

import logging
import subprocess
from typing import List, Optional

logger = logging.getLogger(__name__)


class UndoManager:
    """Save git checkpoints before operations and restore on demand.

    Uses ``git stash`` for lightweight snapshots.  The ``/undo`` command
    restores the most recent checkpoint.
    """

    def __init__(self, project_dir: str = ".") -> None:
        self._project_dir = project_dir
        self._checkpoints: List[str] = []  # stash ref names

    def save_checkpoint(self, label: str = "") -> str:
        """Save current working tree state via ``git stash push``.

        Returns the stash ref name, or empty string on failure.
        """
        if not self._has_git():
            return ""

        full_label = f"opencode-{label}" if label else "opencode-auto"
        try:
            result = subprocess.run(
                ["git", "stash", "push", "-m", full_label],
                cwd=self._project_dir,
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and "No local changes" not in result.stdout:
                ref = result.stdout.strip()
                self._checkpoints.append(ref)
                logger.info("Checkpoint saved: %s", ref)
                return ref
            else:
                # No changes to save — fine
                logger.debug("No changes to checkpoint")
                return ""
        except Exception as e:
            logger.warning("Checkpoint failed: %s", e)
            return ""

    def restore_last(self, keep: bool = False) -> Optional[str]:
        """Restore the most recent checkpoint via ``git stash pop``.

        If *keep* is True, uses ``git stash apply`` instead.
        Returns the diff summary or ``None`` on failure.
        """
        if not self._has_git() or not self._has_stash():
            return None

        try:
            cmd = ["git", "stash", "apply" if keep else "pop"]
            result = subprocess.run(
                cmd, cwd=self._project_dir,
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                logger.warning("Restore failed: %s", result.stderr.strip())
                return result.stderr.strip() or "undo failed"

            if not keep and self._checkpoints:
                self._checkpoints.pop()

            # Get summary of what changed
            return self._get_diff_stat() or "已恢复到上一个检查点"
        except Exception as e:
            return str(e)

    def stash_count(self) -> int:
        """Return number of stashed checkpoints."""
        if not self._has_git():
            return 0
        try:
            result = subprocess.run(
                ["git", "stash", "list"],
                cwd=self._project_dir,
                capture_output=True, text=True, timeout=5,
            )
            return len([l for l in result.stdout.strip().split("\n") if l])
        except Exception:
            return 0

    # --- Internal -------------------------------------------------------------

    def _has_git(self) -> bool:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                cwd=self._project_dir,
                capture_output=True, text=True, timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _has_stash(self) -> bool:
        return self.stash_count() > 0

    def _get_diff_stat(self) -> Optional[str]:
        try:
            result = subprocess.run(
                ["git", "diff", "--stat", "--no-color"],
                cwd=self._project_dir,
                capture_output=True, text=True, timeout=10,
            )
            return result.stdout.strip() or None
        except Exception:
            return None
