"""Status commands — /status, /progress, /cost"""

import time

from wechat_opencode.commands.base import BaseCommandHandler, CommandContext


class StatusCommand(BaseCommandHandler):
    command_name = "status"
    description = "查看当前状态"

    def execute(self, args: str, ctx: CommandContext) -> bool:
        if not ctx.bot:
            return True
        lines = []
        if ctx.exec_queue:
            if ctx.exec_queue.is_busy:
                lines.append("⏳ 监工正在处理消息...")
            pending = ctx.exec_queue.pending_count
            if pending > 0:
                lines.append(f"📋 队列中还有 {pending} 条待处理消息")
        w = ctx.worker.worker if ctx.worker else None
        if w and w.status == "running":
            elapsed = time.time() - w.started_at
            lines.append(f"🤖 执行中: {w.task[:60]}")
            lines.append(f"   已运行: {int(elapsed)}s")
            lines.append(f"   进度间隔: {ctx.worker.progress_interval}s")
        if not lines:
            ctx.bot.send_text("💤 空闲中，没有任务在执行")
        else:
            ctx.bot.send_text("\n".join(lines))
        return True


class ProgressCommand(BaseCommandHandler):
    command_name = "progress"
    description = "进度报告间隔"

    def execute(self, args: str, ctx: CommandContext) -> bool:
        if not ctx.bot:
            return True
        if args:
            try:
                secs = int(args.split()[0])
            except (ValueError, IndexError):
                ctx.bot.send_text("格式: /progress N (N为秒数，最少10秒)")
                return True
            if ctx.worker:
                ctx.worker.set_progress_interval(secs)
            ctx.bot.send_text(f"✅ 进度报告间隔已设为 {max(10, secs)} 秒")
        else:
            interval = ctx.worker.progress_interval if ctx.worker else 300
            ctx.bot.send_text(
                f"当前进度报告间隔: {interval} 秒\n"
                f"修改: /progress N (最少10秒)"
            )
        return True


class CostCommand(BaseCommandHandler):
    command_name = "cost"
    description = "查看费用统计"

    def execute(self, args: str, ctx: CommandContext) -> bool:
        if ctx.bot:
            ctx.bot.send_text(ctx.costs.format_summary())
        return True
