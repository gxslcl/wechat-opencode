"""Help command — /help, /h, /?"""

from wechat_opencode.commands.base import BaseCommandHandler, CommandContext


class HelpCommand(BaseCommandHandler):
    command_name = "help"
    aliases = ["h", "?"]
    description = "查看帮助"

    def execute(self, args: str, ctx: CommandContext) -> bool:
        if not ctx.bot:
            return True
        ctx.bot.send_text(
            "📋 全部指令\n\n"
            "💬 任意文字 — 和监工对话\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "会话管理\n"
            "  /sessions — 查看执行会话列表\n"
            "  /1 /2 /3 — 切换到第 N 个会话\n"
            "  /new — 新建执行会话\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "任务管理\n"
            "  /plan 目标 — 规划并执行\n"
            "  /tasks — 查看任务列表\n"
            "  /task N — 查看任务详情\n"
            "  /status — 查看当前状态\n"
            "  /progress N — 设置进度报告间隔(秒)\n"
            "  /cancel — 取消执行中的任务\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "工具\n"
            "  /screen — 截取电脑桌面\n"
            "  /file 文件名 — 搜索并发送文件\n"
            "  /focus 应用 — 切换窗口到前台\n"
            "  /open 应用/文件 — 打开应用或文件\n"
            "  /desktop — 显示桌面\n"
            "  /min /max — 最小化/最大化\n"
            "  /apps — 运行中的应用\n"
            "  /cost — 查看费用统计\n"
            "  /model — 查看/切换模型\n"
            "  /ppt 主题 — 生成精美PPT\n"
            "  /undo — 撤销上次操作\n"
            "  /cleartasks — 清空任务记录\n"
            "  /restart — 重启服务"
        )
        return True
