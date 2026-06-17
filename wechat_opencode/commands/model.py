"""Model switch command — /model"""

import json
import logging

from wechat_opencode.commands.base import BaseCommandHandler, CommandContext

logger = logging.getLogger(__name__)


class ModelCommand(BaseCommandHandler):
    command_name = "model"
    description = "查看/切换模型"

    def execute(self, args: str, ctx: CommandContext) -> bool:
        if not ctx.bot:
            return True
        if args:
            models = {
                "flash": "deepseek/deepseek-chat",
                "pro": "deepseek/deepseek-v4-pro",
            }
            m = models.get(args.lower())
            if not m:
                ctx.bot.send_text(f"未知模型: {args}。可用: /model flash, /model pro")
                return True

            try:
                with open("opencode.json", "r") as f:
                    cfg = json.load(f)
                cfg["model"] = m
                with open("opencode.json", "w") as f:
                    json.dump(cfg, f, ensure_ascii=False)
            except Exception as e:
                ctx.bot.send_text(f"❌ 更新配置失败: {e}")
                return True

            ctx.bot.send_text(f"✅ 已切换到: {m}")
        else:
            try:
                with open("opencode.json", "r") as f:
                    cfg = json.load(f)
                current = cfg.get("model", "unknown")
            except Exception:
                current = "unknown"
            ctx.bot.send_text(f"当前模型: {current}\n/model flash 或 /model pro 切换")
        return True
