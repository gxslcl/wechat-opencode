"""Session management commands — /sessions, /new"""

from wechat_opencode.commands.base import BaseCommandHandler, CommandContext


class SessionsCommand(BaseCommandHandler):
    command_name = "sessions"
    aliases = ["list", "session"]
    description = "会话列表"

    def execute(self, args: str, ctx: CommandContext) -> bool:
        if not ctx.bot:
            return True

        # Access worker_history from core.py. Since we can't access it via ctx,
        # we use a placeholder. The actual state is maintained in core.py.
        ctx.bot.send_text("暂无执行会话记录")
        return True


class NewCommand(BaseCommandHandler):
    command_name = "new"
    aliases = ["fresh"]
    description = "新建执行会话"

    def execute(self, args: str, ctx: CommandContext) -> bool:
        if not ctx.bot:
            return True
        # 1. Cancel worker
        if ctx.worker:
            ctx.worker.cancel()
        # 2. Clear the execution queue
        cleared = 0
        if ctx.exec_queue:
            cleared = ctx.exec_queue.clear()
        # 3. Abort current supervisor session
        if ctx.supervisor_id:
            try:
                ctx.session._api_post(
                    f"/session/{ctx.supervisor_id}/abort", {}, timeout=5,
                )
            except Exception:
                pass
        ctx.selected_worker_sid = None
        msg = "✅ 已重置"
        if cleared > 0:
            msg += f"，清空队列中 {cleared} 个任务"
        ctx.bot.send_text(msg)
        return True
