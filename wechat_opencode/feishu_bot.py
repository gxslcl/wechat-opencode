"""Feishu (Lark) bot — receive and send messages via Feishu Bot API.

Uses lark-oapi 1.6.8 ws.Client with built-in auto-reconnect, time-windowed
message dedup, async queue processing, and rate-limit handling.

All outgoing messages flow through the shared MessageBus so Web UI and
Feishu clients receive the same replies.
"""

import base64
import json
import logging
import os
import queue
import tempfile
import threading
import time
from typing import Callable, Optional

from wechat_opencode.types import WxMessage

logger = logging.getLogger(__name__)


class FeishuBot:
    """Feishu bot using WebSocket (event-driven) and REST API (sending).

    Usage::

        bot = FeishuBot(app_id, app_secret, on_message=handler)
        bot.start()
        ...
        bot.stop()
    """

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        on_message: Callable[[WxMessage], None],
        dedup_window: float = 300.0,
    ) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._on_message = on_message
        self._running = False
        self._ws_client: Optional["lark_oapi.ws.Client"] = None  # type: ignore[name-defined]
        self._api_client: Optional["lark_oapi.Client"] = None  # type: ignore[name-defined]
        self._last_open_id: Optional[str] = None  # last user who messaged the bot
        # Time-windowed dedup: message_id -> received timestamp
        self._seen_ids: dict[str, float] = {}
        self._dedup_window: float = dedup_window  # seconds before a seen ID expires
        # Rate limiting — set when API returns 999914xx error codes
        self._rate_limited_until: float = 0.0
        # Message bus — publish outgoing messages so Web UI sees them too
        self._bus: Optional["MessageBus"] = None  # type: ignore[name-defined]
        self._bus_source: str = "feishu"  # source tag for bus messages
        # Async message processing — handler ACKs immediately, queue processes later
        self._message_queue: queue.Queue[WxMessage] = queue.Queue()
        self._processor_thread: Optional[threading.Thread] = None

    # --- Lifecycle -----------------------------------------------------------

    def start(self) -> None:
        """Connect to Feishu and start listening for messages."""
        # Disable system proxy — Feishu API must be reached directly.
        # Proxy env vars are cleared for the bot's entire lifetime (restored on stop).
        self._proxy_backup = {}
        for _key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
                       "ALL_PROXY", "all_proxy", "NO_PROXY", "no_proxy"):
            if _key in os.environ:
                self._proxy_backup[_key] = os.environ.pop(_key)
        # Explicitly disable all proxy usage
        os.environ["NO_PROXY"] = "*"
        os.environ["no_proxy"] = "*"
        # Disable Windows registry proxy detection (websockets/requests use this)
        import urllib.request as _ur
        self._orig_getproxies = _ur.getproxies
        _ur.getproxies = lambda: {}

        import lark_oapi as lark
        from lark_oapi.api.im.v1 import P2ImMessageReceiveV1
        from lark_oapi.event.dispatcher_handler import EventDispatcherHandler

        # Create API client (for sending messages)
        self._api_client = (
            lark.Client.builder()
            .app_id(self._app_id)
            .app_secret(self._app_secret)
            .build()
        )

        # Build event handler for receiving messages
        handler = (
            EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self._on_feishu_message)
            .build()
        )

        # Start WebSocket client (auto_reconnect=True is the default in 1.6.8)
        self._ws_client = lark.ws.Client(
            app_id=self._app_id,
            app_secret=self._app_secret,
            event_handler=handler,
        )

        self._running = True
        # Run the WS client in a background thread (it's blocking)
        self._thread = threading.Thread(target=self._ws_client.start, daemon=True)
        self._thread.start()
        # Start async message processor
        self._processor_thread = threading.Thread(target=self._process_queue, daemon=True)
        self._processor_thread.start()
        logger.info("FeishuBot started (app_id=%s)", self._app_id)

    def stop(self) -> None:
        """Disconnect from Feishu."""
        self._running = False
        if self._ws_client is not None:
            try:
                self._ws_client.stop()
            except Exception as e:
                logger.warning("Error stopping Feishu WS client: %s", e)
        if self._processor_thread is not None and self._processor_thread.is_alive():
            self._processor_thread.join(timeout=5.0)
        # Restore proxy environment variables and urllib
        if hasattr(self, "_proxy_backup"):
            os.environ.update(self._proxy_backup)
            self._proxy_backup = {}
        if hasattr(self, "_orig_getproxies"):
            import urllib.request as _ur
            _ur.getproxies = self._orig_getproxies  # type: ignore[assignment]
        logger.info("FeishuBot stopped")

    # --- Message handling (WS thread → ACK immediately) ----------------------

    def _on_feishu_message(self, data: "P2ImMessageReceiveV1") -> None:  # type: ignore[name-defined]
        """Callback from the WS event dispatcher when a message arrives.

        This runs in the WS client thread and MUST return quickly so the
        SDK can ACK the event.  Actual processing is offloaded to the
        message queue processor thread.
        """
        try:
            event = data.event
            if event is None:
                return

            message = event.message
            if message is None:
                return

            msg_id = message.message_id or ""

            # ── Time-windowed dedup ──────────────────────────────────────
            now = time.time()
            if msg_id:
                # Cleanup expired entries periodically (avoids unbounded growth)
                if len(self._seen_ids) > 100:
                    self._seen_ids = {
                        k: v for k, v in self._seen_ids.items()
                        if now - v < self._dedup_window
                    }
                if msg_id in self._seen_ids:
                    logger.debug("Dedup: skipping seen message %s", msg_id)
                    return
                self._seen_ids[msg_id] = now

            # ── Image messages → queue for async download ────────────────
            if message.message_type == "image":
                self._queue_image_message(message, event)
                return

            # ── Only text messages beyond here ───────────────────────────
            if message.message_type != "text":
                return

            # ── Group chat: only process if bot was @mentioned ───────────
            chat_type = message.chat_type or ""
            if chat_type != "p2p":
                mentions = message.mentions or []
                if not mentions:
                    logger.debug(
                        "Skipping group message without @mention (chat_type=%s)",
                        chat_type,
                    )
                    return

            # ── Parse text content ───────────────────────────────────────
            raw_content = message.content or "{}"
            try:
                content_obj = json.loads(raw_content)
                text = content_obj.get("text", "")
            except (json.JSONDecodeError, TypeError):
                text = raw_content

            if not text:
                return

            # ── Extract sender info ──────────────────────────────────────
            sender = event.sender
            sender_id_obj = sender.sender_id if sender else None
            open_id = sender_id_obj.open_id if sender_id_obj else ""
            if open_id:
                self._last_open_id = open_id

            logger.info("Feishu message from %s: %s", open_id, text[:80])

            # ── Queue for async processing (ACK returned immediately) ────
            wx_msg = WxMessage(
                id=msg_id,
                type=1,  # TEXT (same as WeChat)
                sender=open_id,
                roomid=message.chat_id or "",
                content=text,
                timestamp=int(message.create_time or "0"),
            )
            try:
                self._message_queue.put_nowait(wx_msg)
            except queue.Full:
                logger.warning("Message queue full; dropping message %s", msg_id)

        except Exception as e:
            logger.error("Error handling Feishu message: %s", e)

    def _queue_image_message(self, message, event) -> None:
        """Queue an image message for async download — NO blocking I/O here."""
        try:
            raw_content = message.content or "{}"
            content_obj = json.loads(raw_content)
            image_key = content_obj.get("image_key", "")
            if not image_key:
                return

            sender_id = ""
            if event.sender and event.sender.sender_id:
                sender_id = event.sender.sender_id.open_id or ""

            # Queue lightweight task; actual download happens in processor thread
            wx_msg = WxMessage(
                id=message.message_id or "",
                type=3,  # IMAGE type
                sender=sender_id,
                roomid=message.chat_id or "",
                content=image_key,  # store image_key temporarily
                timestamp=int(message.create_time or "0"),
            )
            wx_msg._queued_image_key = image_key  # type: ignore[attr-defined]
            self._message_queue.put_nowait(wx_msg)

        except Exception as e:
            logger.error("Error queuing image message: %s", e)

    # --- Async queue processor (separate thread) ----------------------------

    def _process_queue(self) -> None:
        """Worker thread: consume messages from the queue and forward to handler."""
        while self._running:
            try:
                wx_msg = self._message_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            try:
                if hasattr(wx_msg, "_queued_image_key"):
                    self._download_and_forward_image(wx_msg)
                else:
                    self._on_message(wx_msg)
            except Exception as e:
                logger.error("Error in message processor: %s", e)
            finally:
                self._message_queue.task_done()

    def _download_and_forward_image(self, wx_msg: WxMessage) -> None:
        """Download image from Feishu API and forward to the message handler."""
        try:
            image_key = getattr(wx_msg, "_queued_image_key", "")
            if not image_key or self._api_client is None:
                return

            from lark_oapi.api.im.v1 import GetImageRequest

            resp = self._api_client.im.v1.image.get(
                GetImageRequest.builder().image_key(image_key).build()
            )
            if not resp.success():
                logger.warning("Failed to download image: %s", resp.msg)
                return

            # Save to temp file
            suffix = ".jpg"
            resp_data = resp.data
            if hasattr(resp_data, "file"):
                file_info = resp_data.file
                if file_info.file_name:
                    suffix = f".{file_info.file_name.split('.')[-1]}"
                img_bytes = file_info.data
                if hasattr(img_bytes, "read"):
                    img_bytes = img_bytes.read()
                elif isinstance(img_bytes, bytes):
                    pass
                else:
                    img_bytes = base64.b64decode(img_bytes)
            else:
                img_bytes = resp_data

            if isinstance(img_bytes, str):
                img_bytes = img_bytes.encode()

            fd, path = tempfile.mkstemp(suffix=suffix, prefix="feishu_img_")
            with os.fdopen(fd, "wb") as f:
                f.write(img_bytes)

            logger.info("Image saved to %s (%d bytes)", path, len(img_bytes))

            # Update the WxMessage and forward
            wx_msg.content = f"[图片消息，已保存到: {path}]"
            wx_msg._image_path = path  # type: ignore[attr-defined]
            self._on_message(wx_msg)

        except Exception as e:
            logger.error("Error downloading image: %s", e)

    # --- Rate limiting helpers ----------------------------------------------

    def _check_rate_limited(self) -> bool:
        """Return True if currently rate-limited; skip sends when true."""
        if self._rate_limited_until > time.time():
            logger.debug(
                "Rate limited; skipping send (until %.1f)",
                self._rate_limited_until,
            )
            return True
        return False

    def _handle_rate_limit(self, resp) -> None:
        """Check API response for rate-limit error codes and set cooldown."""
        code = getattr(resp, "code", 0)
        # Feishu rate limit error codes: 99991400 (user), 99991401 (app)
        if code and 99991400 <= code <= 99991500:
            self._rate_limited_until = time.time() + 1.0
            logger.warning("Rate limited (code=%d); pausing sends for 1 s", code)

    # --- Bus integration -----------------------------------------------------

    def set_bus(self, bus: "MessageBus") -> None:  # type: ignore[name-defined]
        """Attach a MessageBus so outgoing messages are visible to all consumers."""
        self._bus = bus

    def _publish_outgoing(self, text: str, open_id: Optional[str]) -> None:
        """Publish an outgoing message to the bus (Web UI + other consumers)."""
        if self._bus is not None:
            self._bus.publish("outgoing", {
                "channel": "outgoing",
                "text": text,
                "role": "assistant",
                "source": self._bus_source,
                "sender": open_id or self._last_open_id or "",
            })

    # --- Send helpers (public API) ------------------------------------------

    def send_text(self, text: str, open_id: Optional[str] = None) -> None:
        """Send a text message to a user by their *open_id*.

        If *open_id* is omitted, the bot replies to the user who last sent
        a message (tracked automatically).
        """
        self._publish_outgoing(text, open_id)

        if self._api_client is None:
            logger.error("Cannot send text: Feishu client not initialized")
            return

        target = open_id or self._last_open_id
        if not target:
            logger.warning("No target open_id available; cannot send Feishu message")
            return

        if self._check_rate_limited():
            return

        from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

        body = (
            CreateMessageRequestBody.builder()
            .msg_type("text")
            .content(json.dumps({"text": text}))
            .receive_id(target)
            .build()
        )

        request = (
            CreateMessageRequest.builder()
            .receive_id_type("open_id")
            .request_body(body)
            .build()
        )

        for attempt in range(2):
            try:
                resp = self._api_client.im.v1.message.create(request)
                self._handle_rate_limit(resp)
                if not resp.success():
                    logger.warning(
                        "Feishu send failed: code=%d msg=%s",
                        resp.code, resp.msg,
                    )
                else:
                    logger.info("Feishu text sent: %s", text[:60])
                    break
            except Exception as e:
                if attempt == 0:
                    logger.warning("Feishu send failed (retrying): %s", e)
                    time.sleep(1)
                else:
                    logger.error("Failed to send Feishu text (2 attempts): %s", e)

    def send_file(self, file_path: str, open_id: Optional[str] = None) -> None:
        """Upload a local file and send it to the user via Feishu."""
        file_name = os.path.basename(file_path)
        self._publish_outgoing(f"📎 发送文件: {file_name}", open_id)

        if self._api_client is None:
            logger.error("Cannot send file: Feishu client not initialized")
            return

        target = open_id or self._last_open_id
        if not target or not os.path.exists(file_path):
            return

        if self._check_rate_limited():
            return

        try:
            file_name = os.path.basename(file_path)
            file_size = os.path.getsize(file_path)

            # Upload file to Feishu
            from lark_oapi.api.im.v1 import CreateFileRequest, CreateFileRequestBody
            f = open(file_path, "rb")
            body = (
                CreateFileRequestBody.builder()
                .file_name(file_name)
                .file_type("stream")
                .file(f)
                .build()
            )
            request = CreateFileRequest.builder().request_body(body).build()
            resp = self._api_client.im.v1.file.create(request)
            f.close()

            self._handle_rate_limit(resp)

            if not resp.success():
                logger.warning("File upload failed: %s", resp.msg)
                return

            file_key = resp.data.file_key
            logger.info(
                "File uploaded: %s (%d bytes, key=%s)",
                file_name, file_size, file_key,
            )

            # Send as message
            from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody
            msg_body = (
                CreateMessageRequestBody.builder()
                .msg_type("file")
                .content(json.dumps({"file_key": file_key}))
                .receive_id(target)
                .build()
            )
            msg_req = (
                CreateMessageRequest.builder()
                .receive_id_type("open_id")
                .request_body(msg_body)
                .build()
            )
            resp2 = self._api_client.im.v1.message.create(msg_req)
            self._handle_rate_limit(resp2)

            if not resp2.success():
                logger.warning(
                    "File message send failed: code=%d msg=%s",
                    resp2.code, resp2.msg,
                )

            logger.info("File sent: %s", file_name)
        except Exception as e:
            logger.error("Failed to send file: %s", e)

    def send_image(self, image_path: str, open_id: Optional[str] = None) -> None:
        """Upload and send an image via Feishu."""
        self._publish_outgoing(f"📸 [图片] {os.path.basename(image_path)}", open_id)
        if self._api_client is None:
            return
        target = open_id or self._last_open_id
        if not target or not os.path.exists(image_path):
            logger.warning(
                "send_image: no target or file not found (target=%s, path=%s)",
                target, image_path,
            )
            return

        if self._check_rate_limited():
            return

        try:
            from lark_oapi.api.im.v1 import CreateImageRequest, CreateImageRequestBody
            f = open(image_path, "rb")
            body = (
                CreateImageRequestBody.builder()
                .image_type("message")
                .image(f)
                .build()
            )
            request = CreateImageRequest.builder().request_body(body).build()
            resp = self._api_client.im.v1.image.create(request)
            f.close()

            self._handle_rate_limit(resp)

            if not resp.success():
                logger.warning("Image upload failed: %s", resp.msg)
                return

            image_key = resp.data.image_key

            from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody
            msg_body = (
                CreateMessageRequestBody.builder()
                .msg_type("image")
                .content(json.dumps({"image_key": image_key}))
                .receive_id(target)
                .build()
            )
            msg_req = (
                CreateMessageRequest.builder()
                .receive_id_type("open_id")
                .request_body(msg_body)
                .build()
            )
            resp2 = self._api_client.im.v1.message.create(msg_req)
            self._handle_rate_limit(resp2)

            if not resp2.success():
                logger.warning(
                    "Image message send failed: code=%d msg=%s",
                    resp2.code, resp2.msg,
                )

            logger.info("Image sent: %s", image_path)
        except Exception as e:
            logger.error("Failed to send image: %s", e)

    def send_card(self, card_data: dict, open_id: Optional[str] = None) -> Optional[str]:
        """Send an interactive card message via Feishu.

        Args:
            card_data: CardKit-compatible card JSON dictionary.
            open_id: Target user's open_id (defaults to last sender).

        Returns:
            The *message_id* of the sent card, or *None* on failure.
        """
        title = card_data.get("header", {}).get("title", {}).get("content", "") if isinstance(card_data, dict) else ""
        self._publish_outgoing(f"[卡片] {title}", open_id)

        if self._api_client is None:
            logger.error("Cannot send card: Feishu client not initialized")
            return None

        target = open_id or self._last_open_id
        if not target:
            logger.warning("No target open_id available; cannot send Feishu card")
            return None

        if self._check_rate_limited():
            return None

        from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

        try:
            body = (
                CreateMessageRequestBody.builder()
                .msg_type("interactive")
                .content(json.dumps(card_data))
                .receive_id(target)
                .build()
            )

            request = (
                CreateMessageRequest.builder()
                .receive_id_type("open_id")
                .request_body(body)
                .build()
            )

            resp = self._api_client.im.v1.message.create(request)
            self._handle_rate_limit(resp)

            if not resp.success():
                logger.warning(
                    "Feishu card send failed: code=%d msg=%s",
                    resp.code, resp.msg,
                )
                return None

            msg_id = resp.data.message_id if resp.data else None
            logger.info("Feishu card sent (msg_id=%s)", msg_id)
            return msg_id

        except Exception as e:
            logger.error("Failed to send Feishu card: %s", e)
            return None

    def edit_message(self, msg_id: str, content: str) -> bool:
        """Edit/update a previously sent message (for progress updates).

        Uses Feishu's ``PATCH /im/v1/messages/{msg_id}`` API to modify
        an existing text message.  For card updates, pass the updated card
        JSON string as *content*.

        Args:
            msg_id: The message_id to update.
            content: New text content.

        Returns:
            *True* if the update succeeded, *False* otherwise.
        """
        if self._api_client is None:
            logger.error("Cannot edit message: Feishu client not initialized")
            return False

        if self._check_rate_limited():
            return False

        from lark_oapi.api.im.v1 import UpdateMessageRequest, UpdateMessageRequestBody

        try:
            body = (
                UpdateMessageRequestBody.builder()
                .msg_type("text")
                .content(json.dumps({"text": content}))
                .build()
            )

            request = (
                UpdateMessageRequest.builder()
                .message_id(msg_id)
                .request_body(body)
                .build()
            )

            resp = self._api_client.im.v1.message.update(request)
            self._handle_rate_limit(resp)

            if not resp.success():
                logger.warning(
                    "Feishu message edit failed: code=%d msg=%s",
                    resp.code, resp.msg,
                )
                return False

            logger.info("Feishu message edited (msg_id=%s)", msg_id)
            return True

        except Exception as e:
            logger.error("Failed to edit Feishu message: %s", e)
            return False
