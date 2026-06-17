"""Window control commands — /desktop, /min, /max, /apps, /focus, /open"""

import time
from typing import Optional

from wechat_opencode.commands.base import BaseCommandHandler, CommandContext
from wechat_opencode.window_manager import (
    focus_window, focus_window_by_index, show_desktop,
    minimize_current, maximize_current, list_apps,
    open_app_or_file, open_by_index,
)


class DesktopCommand(BaseCommandHandler):
    command_name = "desktop"
    description = "显示桌面"

    def execute(self, args: str, ctx: CommandContext) -> bool:
        ok, msg = show_desktop()
        if ctx.bot:
            ctx.bot.send_text(msg)
        return True


class MinCommand(BaseCommandHandler):
    command_name = "min"
    description = "最小化当前窗口"

    def execute(self, args: str, ctx: CommandContext) -> bool:
        ok, msg = minimize_current()
        if ctx.bot:
            ctx.bot.send_text(msg)
        return True


class MaxCommand(BaseCommandHandler):
    command_name = "max"
    description = "最大化当前窗口"

    def execute(self, args: str, ctx: CommandContext) -> bool:
        ok, msg = maximize_current()
        if ctx.bot:
            ctx.bot.send_text(msg)
        return True


class AppsCommand(BaseCommandHandler):
    command_name = "apps"
    description = "列出运行中的应用"

    def execute(self, args: str, ctx: CommandContext) -> bool:
        if ctx.bot:
            ctx.bot.send_text(list_apps())
        return True


class FocusCommand(BaseCommandHandler):
    command_name = "focus"
    description = "切换窗口到前台"

    def execute(self, args: str, ctx: CommandContext) -> bool:
        if not ctx.bot:
            return True
        if not args:
            ctx.bot.send_text(
                "用法: /focus <应用名>\n例如: /focus chrome\n查看所有: /apps"
            )
            return True

        ok, msg = focus_window(args)
        if ok:
            ctx.bot.send_text(msg)
        elif msg.startswith("🔍"):
            # Set focus_query for multi-turn selection (handled in core.py)
            ctx.focus_query = args
            ctx.bot.send_text(msg)
        else:
            ctx.bot.send_text(msg)
        return True


class OpenCommand(BaseCommandHandler):
    command_name = "open"
    description = "打开应用或文件"

    def execute(self, args: str, ctx: CommandContext) -> bool:
        if not ctx.bot:
            return True
        if not args:
            ctx.bot.send_text(
                "用法: /open <应用名或文件名>\n"
                "例如: /open 微信\n"
                "例如: /open 报告.docx"
            )
            return True

        ok, msg, candidates = open_app_or_file(args)
        if ok:
            ctx.bot.send_text(msg)
        elif candidates:
            ctx.open_query = args
            ctx.open_candidates = candidates
            ctx.bot.send_text(msg)
        else:
            ctx.bot.send_text(msg)
        return True
