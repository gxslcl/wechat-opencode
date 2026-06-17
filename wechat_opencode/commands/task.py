"""Task management commands — /tasks, /task N, /cancel, /cleartasks"""

from wechat_opencode.commands.base import BaseCommandHandler, CommandContext


class TasksCommand(BaseCommandHandler):
    command_name = "tasks"
    description = "任务列表"

    def execute(self, args: str, ctx: CommandContext) -> bool:
        if not ctx.bot:
            return True
        tasks = ctx.tracker.list_recent(10)
        if not tasks:
            ctx.bot.send_text("暂无任务记录")
            return True

        lines = ["📋 任务列表（最近10个）："]
        status_icon = {"done": "✅", "failed": "❌", "running": "⏳"}
        for i, t in enumerate(tasks, 1):
            icon = status_icon.get(t.status, "⬜")
            lines.append(f"{i}. {icon} {t.goal[:60]}")
        lines.append("")
        lines.append("回复 /task N 查看详情")
        ctx.bot.send_text("\n".join(lines))
        return True


class TaskDetailCommand(BaseCommandHandler):
    command_name = "task"
    description = "任务详情"

    def execute(self, args: str, ctx: CommandContext) -> bool:
        if not ctx.bot:
            return True
        try:
            num = int(args.split()[0]) if args else 0
        except (ValueError, IndexError):
            ctx.bot.send_text("格式: /task N (N为编号)")
            return True

        tasks = ctx.tracker.list_recent(20)
        if num < 1 or num > len(tasks):
            ctx.bot.send_text(f"❌ 无效编号 {num}，请发送 /tasks 查看列表")
            return True

        task = tasks[num - 1]
        status_map = {"pending": "⬜", "running": "⏳", "done": "✅", "failed": "❌"}
        lines = [f"📌 任务 #{num}: {task.goal}", f"状态: {status_map.get(task.status, task.status)}"]
        if task.steps:
            lines.append("步骤:")
            for s in task.steps:
                icon = status_map.get(s.status, "⬜")
                desc = s.description[:50]
                lines.append(f"  {icon} {desc}")
                if s.output and s.output.strip():
                    out = s.output[:100]
                    lines.append(f"      {out}")
        ctx.bot.send_text("\n".join(lines))
        return True


class CancelCommand(BaseCommandHandler):
    command_name = "cancel"
    description = "取消任务"

    def execute(self, args: str, ctx: CommandContext) -> bool:
        if not ctx.bot:
            return True
        # 1. Cancel worker execution (if running)
        worker_cancelled = ctx.worker and ctx.worker.cancel()

        # 2. Clear queued commands from supervisor queue
        cleared = 0
        if ctx.exec_queue:
            cleared = ctx.exec_queue.clear()

        # 3. Abort the current supervisor session (force-unblock it)
        session_aborted = False
        if ctx.supervisor_id:
            try:
                ctx.session._api_post(
                    f"/session/{ctx.supervisor_id}/abort", {}, timeout=5,
                )
                session_aborted = True
            except Exception:
                pass

        parts = []
        if worker_cancelled:
            parts.append("Worker任务已取消")
        if cleared > 0:
            parts.append(f"队列中 {cleared} 个待执行任务已清空")
        if session_aborted:
            parts.append("当前执行已中断")
        if not parts:
            ctx.bot.send_text("没有正在执行的任务或队列中的任务")
            return True

        ctx.bot.send_text(f"❌ 已取消: {'，'.join(parts)}")
        return True


class ClearTasksCommand(BaseCommandHandler):
    command_name = "cleartasks"
    description = "清空任务记录"

    def execute(self, args: str, ctx: CommandContext) -> bool:
        if not ctx.bot:
            return True
        # Clear task tracking records
        count = ctx.tracker.clear_all()
        # Also clear the execution queue
        q_cleared = 0
        if ctx.exec_queue:
            q_cleared = ctx.exec_queue.clear()
        parts = []
        if count > 0:
            parts.append(f"已清空 {count} 条任务记录")
        if q_cleared > 0:
            parts.append(f"队列中 {q_cleared} 个待执行任务已清空")
        if not parts:
            ctx.bot.send_text("✅ 没有待清空的任务")
            return True
        ctx.bot.send_text(f"✅ {'，'.join(parts)}")
        return True
