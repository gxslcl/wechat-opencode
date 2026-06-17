"""Command handler registry — maps command names to handler classes."""

from typing import Optional

from wechat_opencode.commands.base import BaseCommandHandler, CommandContext

_registry: dict[str, type[BaseCommandHandler]] = {}
_primary_names: dict[str, str] = {}  # alias → primary name
_descriptions: dict[str, str] = {}  # primary name → description


def register(handler_cls: type[BaseCommandHandler]) -> None:
    """Register a command handler class."""
    inst = handler_cls()
    primary = inst.command_name
    _registry[primary] = handler_cls
    _primary_names[primary] = primary
    _descriptions[primary] = inst.description
    for alias in inst.aliases:
        _registry[alias] = handler_cls
        _primary_names[alias] = primary


def get_handler(name: str) -> Optional[BaseCommandHandler]:
    """Get a handler instance by command name (or alias)."""
    cls = _registry.get(name)
    return cls() if cls else None


def resolve_abbreviation(abbr: str) -> list[str]:
    """Find all primary command names matching the abbreviation prefix."""
    matches = set()
    for name in _registry:
        if name.startswith(abbr):
            primary = _primary_names.get(name, name)
            matches.add(primary)
    return sorted(matches)


def get_all_commands() -> list[tuple[str, list[str], str]]:
    """Return all registered commands as (primary, aliases, description)."""
    result: dict[str, tuple[str, list[str], str]] = {}
    for name, primary in _primary_names.items():
        if primary not in result:
            result[primary] = (primary, [], _descriptions.get(primary, ""))
        if name != primary:
            result[primary][1].append(name)
    return list(result.values())


# Lazy import all handlers to register them
def _init() -> None:
    from wechat_opencode.commands.help import HelpCommand
    from wechat_opencode.commands.screen import ScreenCommand
    from wechat_opencode.commands.window import (
        DesktopCommand, MinCommand, MaxCommand,
        AppsCommand, FocusCommand, OpenCommand,
    )
    from wechat_opencode.commands.file import FileCommand
    from wechat_opencode.commands.session import (
        SessionsCommand, NewCommand,
    )
    from wechat_opencode.commands.task import (
        TasksCommand, TaskDetailCommand,
        CancelCommand, ClearTasksCommand,
    )
    from wechat_opencode.commands.status import (
        StatusCommand, ProgressCommand, CostCommand,
    )
    from wechat_opencode.commands.model import ModelCommand
    from wechat_opencode.commands.ppt import PptCommand
    from wechat_opencode.commands.undo import UndoCommand
    from wechat_opencode.commands.system import RestartCommand, CompactCommand, CronCommand
    from wechat_opencode.commands.plan import PlanCommand
    for cls in [
        HelpCommand, ScreenCommand,
        DesktopCommand, MinCommand, MaxCommand,
        AppsCommand, FocusCommand, OpenCommand,
        FileCommand,
        SessionsCommand, NewCommand,
        TasksCommand, TaskDetailCommand,
        CancelCommand, ClearTasksCommand,
        StatusCommand, ProgressCommand, CostCommand,
        ModelCommand,
        PptCommand,
        UndoCommand,
        RestartCommand, CompactCommand, CronCommand,
        PlanCommand,
    ]:
        register(cls)


_init()
