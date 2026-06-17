"""Base command handler — abstract class for all meta-commands."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from wechat_opencode.config import Config
    from wechat_opencode.cost_tracker import CostTracker
    from wechat_opencode.queue import ExecutionQueue
    from wechat_opencode.session import OpenCodeSession
    from wechat_opencode.task_tracker import TaskTracker
    from wechat_opencode.types import BotABC
    from wechat_opencode.undo import UndoManager
    from wechat_opencode.worker import WorkerManager


@dataclass
class CommandContext:
    """Dependencies injected into every command handler."""

    bot: "BotABC"
    session: "OpenCodeSession"
    worker: "WorkerManager"
    tracker: "TaskTracker"
    costs: "CostTracker"
    undo: "UndoManager"
    supervisor_id: str
    exec_queue: "ExecutionQueue"
    config: "Config"
    # Internal state set by core.py before calling execute
    cmd_selection: Optional[list] = None
    focus_query: Optional[str] = None
    open_query: Optional[str] = None
    open_candidates: Optional[list] = None
    selected_worker_sid: Optional[str] = None


class BaseCommandHandler(ABC):
    """Base class for a /command handler.
    
    Subclasses override execute() to handle the command.
    Registration is automatic via the commands registry in __init__.py.
    """

    @property
    @abstractmethod
    def command_name(self) -> str:
        """Primary command name (e.g. 'help', 'screen')."""

    @property
    def aliases(self) -> list[str]:
        """Alternative names that map to this command."""
        return []

    @property
    def description(self) -> str:
        """Human-readable description of what this command does."""
        return ""

    @abstractmethod
    def execute(self, args: str, ctx: CommandContext) -> bool:
        """Execute the command.
        
        Args:
            args: Everything after the command name (e.g. for '/model flash', args='flash')
            ctx: Injected dependencies
            
        Returns:
            True if the command was handled, False if it should fall through to LLM.
        """
        ...
