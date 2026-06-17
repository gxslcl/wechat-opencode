"""Undo command — /undo"""

from wechat_opencode.commands.base import BaseCommandHandler, CommandContext


class UndoCommand(BaseCommandHandler):
    command_name = "undo"
    description = "撤销上次操作"

    def execute(self, args: str, ctx: CommandContext) -> bool:
        if not ctx.bot:
            return True
        result = ctx.undo.restore_last()
        if result:
            ctx.bot.send_text(f"⏪ 已撤销上一步操作\n{result}")
        else:
            ctx.bot.send_text("⏪ 没有可撤销的操作")
        return True
