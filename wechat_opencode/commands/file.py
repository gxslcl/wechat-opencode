"""File command — /file"""

import os
import time
import logging

from wechat_opencode.commands.base import BaseCommandHandler, CommandContext
from wechat_opencode.types import Command, WxMessage

logger = logging.getLogger(__name__)


class FileCommand(BaseCommandHandler):
    command_name = "file"
    description = "搜索并发送文件"

    def execute(self, args: str, ctx: CommandContext) -> bool:
        if not ctx.bot or not ctx.exec_queue or not ctx.supervisor_id:
            return True

        if not args:
            ctx.bot.send_text(
                "用法: /file <路径或描述>\n"
                "明确路径: /file C:/Users/1/Desktop/报告.docx\n"
                "模糊描述: /file 配置文件"
            )
            return True

        logger.info("File command: query=%s", args)

        # Absolute path mode
        if os.path.isabs(args):
            norm = os.path.normpath(args)
            if os.path.isfile(norm):
                self._send_file_and_notify(ctx, norm)
                return True
            prompt = self._build_interaction_prompt(
                args, extra=f"用户提供了一个绝对路径但文件不存在: {norm}\n请告诉用户该路径不存在，然后帮助用户找到文件。"
            )
        else:
            prompt = self._build_interaction_prompt(args)

        cmd = Command(
            original_message=WxMessage(
                id="file", type=1, sender="system", roomid="",
                content=args, timestamp=int(time.time()),
            ),
            content=prompt,
            timestamp=int(time.time()),
            session_id=ctx.supervisor_id,
        )
        ctx.exec_queue.submit(cmd)
        ctx.bot.send_text(f"🔍 正在帮你找文件: {args}")
        return True

    def _send_file_and_notify(self, ctx: CommandContext, path: str) -> None:
        if not ctx.bot:
            return
        if not os.path.isfile(path):
            ctx.bot.send_text(f"❌ 文件不存在: {path}")
            return

        name = os.path.basename(path)
        try:
            size_kb = os.path.getsize(path) / 1024
        except OSError:
            size_kb = 0
        size_str = f"{size_kb:.1f}KB" if size_kb < 1024 else f"{size_kb / 1024:.1f}MB"

        ctx.bot.send_text(f"📎 发送文件: {name} ({size_str})")
        try:
            ctx.bot.send_file(path)
        except Exception as e:
            logger.error("Failed to send file %s: %s", path, e)
            ctx.bot.send_text(f"❌ 发送失败: {e}")

    def _build_interaction_prompt(self, query: str, extra: str = "") -> str:
        return f"""用户想获取文件: "{query}"
{extra}
请按以下流程帮助用户找到并发送文件，每次只做一个步骤:

**第1步 - 确认位置:**
先询问用户文件大概在哪个目录，列出常见位置供选择:
  1. 桌面 (C:\\Users\\1\\Desktop)
  2. 下载 (C:\\Users\\1\\Downloads)
  3. 文档 (C:\\Users\\1\\Documents)
  4. D盘根目录 (D:\\)
  5. E盘根目录 (E:\\)
  6. 微信接收文件 (C:\\Users\\1\\Documents\\WeChat Files)
  7. 其他（请用户输入完整路径）

**第2步 - 列出文件:**
用户选择位置后，用 list 工具列出该目录下的所有文件（跳过子目录），
按修改时间倒序排列，最多显示 30 个文件，带编号。
格式: 1. 文件名 (大小) - 修改时间

**第3步 - 确认发送:**
用户通过编号或文件名选择后，确认文件存在，回复:
[FILE: <完整绝对路径>]

用户也可以说"搜索子目录"让系统递归搜索，
或者说具体关键词缩小范围。

重要: 每次只展示一个步骤的结果，等用户回复后再进行下一步。"""
