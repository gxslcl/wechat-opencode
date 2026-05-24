"""WeChatFerry message bridge — receive and send WeChat messages."""

import logging
import queue
import subprocess
import threading
from typing import Callable, List, Optional

from wechat_opencode.config import Config
from wechat_opencode.types import MessageType, WxMessage

logger = logging.getLogger(__name__)


class WeChatBridge:
    """Bridges WeChatFerry with the application message pipeline.

    On start, the bridge looks up a contact whose name or remark matches
    ``bot_remark`` (default ``"机器人"``).  Only text messages from that
    contact are forwarded to the callback, and responses are sent back to
    the same contact.

    If no matching contact is found the bridge falls back to processing
    self-sent messages (the ``filehelper`` pattern) so existing setups
    continue to work.
    """

    def __init__(self, config: Config, on_message: Callable[[WxMessage], None]) -> None:
        self._config = config
        self._on_message = on_message
        self._wcf = None  # type: ignore[assignment]
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._bot_wxid: Optional[str] = None  # resolved contact wxid
        self._bot_mode: bool = False  # True = bot contact mode, False = filehelper fallback

    # --- Lifecycle -----------------------------------------------------------

    def start(self) -> None:
        """Initialize WeChatFerry connection, resolve bot contact, and start listener."""
        from wcferry import Wcf  # lazy import — allows testing without WeChat

        self._wcf = Wcf()
        self._wcf.enable_receiving_msg()

        # Resolve the bot contact (don't fail if not found — fall back)
        self._bot_wxid = self._resolve_bot_contact(self._config.wechat.bot_remark)
        if self._bot_wxid:
            self._bot_mode = True
            logger.info("Bot contact resolved: %s (%s)", self._config.wechat.bot_remark, self._bot_wxid)
        else:
            self._bot_mode = False
            logger.warning(
                "No contact matching '%s' found — falling back to filehelper mode",
                self._config.wechat.bot_remark,
            )

        self._running = True
        self._thread = threading.Thread(target=self._message_loop, daemon=True)
        self._thread.start()
        logger.info("WeChatBridge started (mode=%s)", "bot" if self._bot_mode else "filehelper")

    def stop(self) -> None:
        """Stop receiving messages and disconnect from WeChatFerry."""
        self._running = False
        if self._wcf is not None:
            try:
                self._wcf.disable_receiving_msg()
            except Exception as e:
                logger.warning("Error disabling wcferry receiving: %s", e)
        logger.info("WeChatBridge stopped")

    # --- Contact resolution --------------------------------------------------

    def _resolve_bot_contact(self, remark: str) -> Optional[str]:
        """Search contacts for one whose ``remark`` or ``name`` matches *remark*.

        Returns the contact's ``wxid``, or ``None`` if not found.
        """
        try:
            contacts: List[dict] = self._wcf.get_contacts()
        except Exception as e:
            logger.error("Failed to get contacts: %s", e)
            return None

        remark_lower = remark.lower()
        for c in contacts:
            if c.get("remark", "").lower() == remark_lower or c.get("name", "").lower() == remark_lower:
                return c.get("wxid")
        return None

    # --- Send helpers --------------------------------------------------------

    def send_text(self, text: str, wxid: Optional[str] = None) -> None:
        """Send a text message to the given *wxid* (default: bot contact / filehelper)."""
        if self._wcf is None:
            logger.error("Cannot send text: wcferry not initialized")
            return
        target = wxid or self._bot_wxid or self._config.wechat.filehelper_wxid
        try:
            self._wcf.send_text(text, target)
        except Exception as e:
            logger.error("Failed to send text to %s: %s", target, e)

    def send_file(self, path: str, wxid: Optional[str] = None) -> None:
        """Send a file to the specified wxid (default: bot contact / filehelper)."""
        if self._wcf is None:
            logger.error("Cannot send file: wcferry not initialized")
            return
        target = wxid or self._bot_wxid or self._config.wechat.filehelper_wxid
        try:
            self._wcf.send_file(path, target)
        except Exception as e:
            logger.error("Failed to send file to %s: %s", target, e)

    # --- Health checks -------------------------------------------------------

    def is_wechat_running(self) -> bool:
        """Check if WeChat.exe process is running."""
        try:
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq WeChat.exe"],
                capture_output=True, text=True, timeout=5,
            )
            return "WeChat.exe" in result.stdout
        except Exception:
            return False

    def get_self_wxid(self) -> str:
        """Get the logged-in user's wxid."""
        if self._wcf is None:
            return ""
        try:
            return self._wcf.get_self_wxid()
        except Exception as e:
            logger.error("Failed to get self wxid: %s", e)
            return ""

    # --- Message loop --------------------------------------------------------

    def _message_loop(self) -> None:
        """Background thread that polls for WeChat messages."""
        while self._running:
            try:
                msg = self._wcf.get_msg()
            except queue.Empty:
                continue  # no message yet, keep polling

            logger.debug(
                "Raw msg: type=%d sender=%s roomid=%s from_self=%s content=%s",
                msg.type, msg.sender, msg.roomid, msg.from_self(),
                msg.content[:80] if msg.content else "(empty)",
            )

            # Only process text messages
            if msg.type != MessageType.TEXT:
                logger.debug("Filtered: type=%d != TEXT", msg.type)
                continue

            if self._bot_mode:
                # Bot mode: only accept messages from the resolved bot contact
                if msg.sender != self._bot_wxid:
                    logger.debug("Filtered: sender=%s != bot_wxid=%s", msg.sender, self._bot_wxid)
                    continue
            else:
                # Fallback mode: accept self-sent messages (via filehelper)
                if not msg.from_self():
                    logger.debug("Filtered: not from_self (sender=%s)", msg.sender)
                    continue

            logger.info(
                "Command received: sender=%s content=%s",
                msg.sender, msg.content[:80],
            )

            wx_msg = WxMessage(
                id=str(msg.id),
                type=msg.type,
                sender=msg.sender,
                roomid=getattr(msg, "roomid", ""),
                content=msg.content,
                timestamp=msg.ts,
            )
            try:
                self._on_message(wx_msg)
            except Exception as e:
                logger.error("Error in message callback: %s", e)
