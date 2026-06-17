"""PPT generation command — /ppt"""

from wechat_opencode.commands.base import BaseCommandHandler, CommandContext
from wechat_opencode.ppt_designer import get_designer_prompt


class PptCommand(BaseCommandHandler):
    command_name = "ppt"
    description = "生成PPT"

    def execute(self, args: str, ctx: CommandContext) -> bool:
        if not ctx.bot:
            return True
        if not args:
            ctx.bot.send_text("用法: /ppt 主题\n例如: /ppt AI发展趋势")
            return True

        if not ctx.worker:
            ctx.bot.send_text("❌ PPT 设计任务启动失败")
            return True

        ctx.worker.cancel()
        ctx.selected_worker_sid = None

        if ctx.worker.start_with_prompt(args, get_designer_prompt()):
            ctx.bot.send_text(
                f"🎨 PPT 设计师已就位\n"
                f"主题: {args}\n设计师会先确认参数"
            )
        else:
            ctx.bot.send_text("❌ PPT 设计任务启动失败")
        return True
