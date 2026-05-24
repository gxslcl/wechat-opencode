"""Context injector — enrich opencode prompts with project information."""

import logging
import os
from typing import List, Optional

from wechat_opencode.config import Config

logger = logging.getLogger(__name__)


class ContextInjector:
    """Builds a concise context prefix to help opencode understand the project.

    Injects:
    - Project root directory name
    - Recent task results (from the task tracker)
    """

    def __init__(self, config: Config) -> None:
        self._project_dir = config.opencode.project_dir

    def build(self, recent_results: Optional[List[str]] = None) -> str:
        """Return a concise context string to prepend before the user command."""
        parts = ["[上下文]"]

        dir_name = os.path.basename(self._project_dir.rstrip("/\\"))
        parts.append(f"工作目录: {dir_name}")

        if recent_results:
            parts.append("最近任务: " + " | ".join(recent_results[:3]))

        parts.append("")
        return "\n".join(parts)
