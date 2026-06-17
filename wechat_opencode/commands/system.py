"""System commands — /stop, /restart, /compact, /cron"""

import logging
import time
from typing import Optional

from wechat_opencode.commands.base import BaseCommandHandler, CommandContext
from wechat_opencode.scheduler import CronScheduler

logger = logging.getLogger(__name__)

# Global scheduler instance — set by core.py at startup
_scheduler: Optional[CronScheduler] = None


def set_scheduler(sched: CronScheduler) -> None:
    """Inject the cron scheduler instance from core.py."""
    global _scheduler
    _scheduler = sched


class RestartCommand(BaseCommandHandler):
    command_name = "restart"
    aliases = ["stop"]
    description = "重启服务"

    def execute(self, args: str, ctx: CommandContext) -> bool:
        if ctx.bot:
            ctx.bot.send_text("🔄 正在重启服务...")
        # Trigger restart via core's _restart_services — needs reference to it.
        # We set a flag that core.py checks after command execution.
        ctx._restart_requested = True  # type: ignore[attr-defined]
        return True


class CompactCommand(BaseCommandHandler):
    command_name = "compact"
    description = "压缩对话上下文"

    def execute(self, args: str, ctx: CommandContext) -> bool:
        if not ctx.bot or not ctx.supervisor_id:
            ctx.bot.send_text("❌ 监工会话未就绪") if ctx.bot else None
            return True
        ctx.bot.send_text("🔄 正在压缩对话上下文...")
        try:
            result = ctx.session.execute(
                "/compact", session_id=ctx.supervisor_id, timeout=60,
            )
            ctx.bot.send_text(f"✅ 上下文已压缩\n{result.output[:200]}")
        except Exception as e:
            logger.error("Compact failed: %s", e)
            ctx.bot.send_text(f"❌ 压缩失败: {e}")
        return True


class CronCommand(BaseCommandHandler):
    command_name = "cron"
    description = "定时任务管理"

    def execute(self, args: str, ctx: CommandContext) -> bool:
        if not ctx.bot:
            return True
        if not _scheduler:
            ctx.bot.send_text("❌ 定时任务系统未就绪")
            return True

        parts = args.strip().split(maxsplit=2)
        subcmd = parts[0] if parts else ""

        if subcmd == "add" and len(parts) >= 3:
            schedule_expr = parts[1]
            prompt = parts[2]
            job_id = _scheduler.add_job(schedule_expr, prompt)
            if job_id:
                ctx.bot.send_text(
                    f"✅ 定时任务已创建\n"
                    f"  ID: {job_id}\n"
                    f"  时间: {schedule_expr}\n"
                    f"  任务: {prompt}\n\n"
                    f"使用 /cron list 查看所有任务"
                )
            else:
                ctx.bot.send_text(
                    f"❌ 无法解析定时表达式\n"
                    f"支持格式:\n"
                    f"  /cron add 每天 09:00 发送AI资讯\n"
                    f"  /cron add 每30分钟 检查服务器状态\n"
                    f"  /cron add 周一到周五 08:00 日报"
                )
            return True

        if subcmd == "list" or not subcmd:
            jobs = _scheduler.list_jobs()
            if not jobs:
                ctx.bot.send_text("📋 没有定时任务\n使用 /cron add 添加")
                return True
            lines = ["📋 定时任务列表:"]
            for j in jobs:
                status = "✅" if j.enabled else "⏸️"
                last = f"上次执行: {int(time.time() - j.last_run)}秒前" if j.last_run else "尚未执行"
                lines.append(f"  {status} #{j.id} {j.schedule_text}")
                lines.append(f"     任务: {j.prompt[:40]}")
                lines.append(f"     执行: {j.run_count}次, {last}")
            ctx.bot.send_text("\n".join(lines))
            return True

        if subcmd == "remove" and len(parts) >= 2:
            job_id = parts[1]
            if _scheduler.remove_job(job_id):
                ctx.bot.send_text(f"✅ 已删除定时任务: {job_id}")
            else:
                ctx.bot.send_text(f"❌ 未找到任务: {job_id}")
            return True

        ctx.bot.send_text(
            "📋 定时任务命令\n\n"
            "添加:\n"
            "  /cron add <时间> <任务>\n"
            "  例: /cron add 每天 09:00 发送AI资讯\n"
            "  例: /cron add 每30分钟 检查服务器\n"
            "  例: /cron add 周一到周五 08:00 日报\n\n"
            "管理:\n"
            "  /cron list  — 查看所有任务\n"
            "  /cron remove <ID> — 删除任务"
        )
        return True
