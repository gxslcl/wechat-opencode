"""Plan command — /plan <goal>"""

import time

from wechat_opencode.commands.base import BaseCommandHandler, CommandContext
from wechat_opencode.types import Command, WxMessage


class PlanCommand(BaseCommandHandler):
    command_name = "plan"
    description = "规划并执行"

    def execute(self, args: str, ctx: CommandContext) -> bool:
        if not ctx.bot or not ctx.exec_queue:
            return True
        if not args:
            ctx.bot.send_text("用法: /plan 目标\n例如: /plan 写一个天气爬虫")
            return True

        recent = ctx.tracker.get_recent_results(5)
        from wechat_opencode.context import ContextInjector
        injector = ContextInjector(ctx.config)
        context_prefix = injector.build(recent_results=recent)

        plan_prompt = (
            f"{context_prefix}\n\n"
            f"🎯 任务目标: {args}\n\n"
            "请按以下流程操作：\n"
            "1. 先分析需求，列出完成目标所需步骤\n"
            "2. 逐步执行每个步骤\n"
            "3. 遇到错误先自行修复\n"
            "4. 完成后总结执行结果"
        )
        ctx.tracker.start_task(f"🎯 {args}", steps=["分析需求", "逐步执行", "验证结果"])

        cmd = Command(
            original_message=WxMessage(
                id="plan", type=1, sender="system", roomid="",
                content=args, timestamp=0,
            ),
            content=plan_prompt,
            timestamp=int(time.time()),
            session_id="__new__",
        )
        ctx.exec_queue.submit(cmd)
        ctx.bot.send_text(f"🎯 规划任务: {args}")
        return True
