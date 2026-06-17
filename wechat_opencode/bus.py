"""Message bus — centralized pub/sub for all messages (Feishu, Web, replies)."""

import logging
import threading
import time
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)


class MessageBus:
    """Thread-safe pub/sub message bus.

    All messages — incoming (Feishu/Web) and outgoing (replies/progress) —
    flow through this bus.  Subscribers receive messages by channel::

        bus = MessageBus()
        bus.subscribe("incoming", on_user_message)
        bus.subscribe("outgoing", on_bot_reply)
        bus.publish("incoming", {...})   # triggers on_user_message
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._messages: List[dict] = []
        self._subscribers: dict[str, List[Callable]] = {}
        self._last_id: int = 0

    # ── Publish / Subscribe ──────────────────────────────────────────────

    def subscribe(self, channel: str, callback: Callable) -> None:
        """Register a callback for *channel* events.

        Supported channels: ``"incoming"`` (user messages from any source),
        ``"outgoing"`` (bot replies/progress).
        """
        with self._lock:
            self._subscribers.setdefault(channel, []).append(callback)

    def publish(self, channel: str, msg: dict) -> None:
        """Publish a message dict to *channel*.

        The dict SHOULD contain at least:

        - ``id`` — unique message ID (auto-assigned if empty)
        - ``text`` — message content
        - ``role`` — ``"user"`` | ``"assistant"``
        - ``source`` — ``"feishu"`` | ``"web"``
        - ``sender`` — open_id for Feishu, ``"web"`` for Web UI
        - ``timestamp`` — unix seconds
        """
        with self._lock:
            if not msg.get("id"):
                self._last_id += 1
                msg["id"] = f"bus_{self._last_id}"
            if "timestamp" not in msg:
                msg["timestamp"] = time.time()
            self._messages.append(msg)

            for cb in self._subscribers.get(channel, []):
                try:
                    cb(msg)
                except Exception as e:
                    logger.error("Bus subscriber error on channel=%s: %s", channel, e)

    # ── Read ─────────────────────────────────────────────────────────────

    def get_messages(
        self, since_id: str = "", limit: int = 50,
        channel: Optional[str] = None,
    ) -> List[dict]:
        """Return messages after *since_id*, newest first, capped at *limit*.

        If *channel* is set, only return messages from that channel.
        """
        with self._lock:
            idx = 0
            if since_id:
                for i, m in enumerate(self._messages):
                    if m.get("id") == since_id:
                        idx = i + 1
                        break
            result = self._messages[idx:]
            if channel is not None:
                result = [m for m in result if m.get("channel") == channel]
            return result[-limit:]

    def get_history(self, limit: int = 5) -> str:
        """Format recent messages as context text for LLM prompts.

        Returns something like::

            [对话历史]
            用户: 你叫什么名字？
            助手: 我叫小助手！

        Filters out status/notification lines that start with emoji
        (📎 🚀 ✅ ❌ ⏳ 🎯 ❓ ⚠️ 💰 📋 📸 etc.) since they are noise
        for the LLM.
        """
        _SKIP_PREFIXES = ("📎", "🚀", "✅", "❌", "⏳", "🎯", "❓", "⚠️", "💰", "📋", "📸", "🔄", "⏪", "🔍")

        with self._lock:
            recent = self._messages[-limit * 2:]  # grab enough
        lines: List[str] = []
        for m in recent:
            role_label = "用户" if m.get("role") == "user" else "助手"
            text = m.get("text", "").strip()
            if not text:
                continue
            # Skip notification/status lines
            if any(text.startswith(p) for p in _SKIP_PREFIXES):
                continue
            lines.append(f"{role_label}: {text}")
        if lines:
            return "[对话历史]\n" + "\n".join(lines)
        return ""

    @property
    def last_id(self) -> str:
        """Return the ID of the most recent message, or empty string."""
        with self._lock:
            return self._messages[-1]["id"] if self._messages else ""
