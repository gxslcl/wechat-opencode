"""Message router — prefix filter and command extraction."""

import logging
from typing import Optional

from wechat_opencode.config import Config
from wechat_opencode.types import Command, WxMessage

logger = logging.getLogger(__name__)


class MessageRouter:
    """Routes WeChat messages — only /oc-prefixed text becomes a Command."""

    def __init__(self, config: Config) -> None:
        self._prefix = config.wechat.prefix.lower()

    def route(self, message: WxMessage) -> Optional[Command]:
        """Check prefix and extract command. Returns None if not a command."""
        if not self.is_command(message):
            return None

        content = self.extract_command(message)
        if not content:
            return None  # empty command like "/oc" with nothing after

        return Command(
            original_message=message,
            content=content,
            timestamp=message.timestamp,
        )

    def is_command(self, message: WxMessage) -> bool:
        """Check if message starts with the configured prefix (case-insensitive)."""
        return message.content.strip().lower().startswith(self._prefix)

    def extract_command(self, message: WxMessage) -> str:
        """Strip prefix and leading whitespace from message content."""
        content = message.content.strip()
        # Remove the prefix
        rest = content[len(self._prefix):]
        return rest.strip()
