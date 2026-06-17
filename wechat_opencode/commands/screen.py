"""Screen capture command — /screen, /screenshot"""

from wechat_opencode.commands.base import BaseCommandHandler, CommandContext
from wechat_opencode.screenshot import capture_desktop


class ScreenCommand(BaseCommandHandler):
    command_name = "screen"
    aliases = ["screenshot"]
    description = "截取电脑桌面"

    def execute(self, args: str, ctx: CommandContext) -> bool:
        if not ctx.bot:
            return True
        ctx.bot.send_text("📸 正在截图...")
        path = capture_desktop()
        if path:
            ctx.bot.send_image(path)
        else:
            ctx.bot.send_text("❌ 截图失败（Playwright 未安装或出错）")
        return True
