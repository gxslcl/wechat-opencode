"""Feishu (Lark) bot — receive and send messages via Feishu Bot API."""

import base64
import json
import logging
import os
import tempfile
import threading
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
    ) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._on_message = on_message
        self._running = False
        self._ws_client: Optional["lark_oapi.ws.Client"] = None  # type: ignore[name-defined]
        self._api_client: Optional["lark_oapi.Client"] = None  # type: ignore[name-defined]
        self._last_open_id: Optional[str] = None  # last user who messaged the bot
        self._recent_texts: list = []  # dedup: last 20 sent texts

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

        # Start WebSocket client (auto-reconnect by default)
        self._ws_client = lark.ws.Client(
            app_id=self._app_id,
            app_secret=self._app_secret,
            event_handler=handler,
        )

        self._running = True
        # Run the WS client in a background thread (it's blocking)
        self._thread = threading.Thread(target=self._ws_client.start, daemon=True)
        self._thread.start()
        logger.info("FeishuBot started (app_id=%s)", self._app_id)

    def stop(self) -> None:
        """Disconnect from Feishu."""
        self._running = False
        if self._ws_client is not None:
            try:
                self._ws_client.stop()
            except Exception as e:
                logger.warning("Error stopping Feishu WS client: %s", e)
        # Restore proxy environment variables and urllib
        if hasattr(self, "_proxy_backup"):
            os.environ.update(self._proxy_backup)
            self._proxy_backup = {}
        if hasattr(self, "_orig_getproxies"):
            import urllib.request as _ur
            _ur.getproxies = self._orig_getproxies  # type: ignore[assignment]
        logger.info("FeishuBot stopped")

    # --- Message handling ----------------------------------------------------

    def _on_feishu_message(self, data: "P2ImMessageReceiveV1") -> None:  # type: ignore[name-defined]
        """Callback from the WS event dispatcher when a message arrives."""
        try:
            event = data.event
            if event is None:
                return

            message = event.message
            if message is None:
                return

            # Handle image messages
            if message.message_type == "image":
                self._handle_image_message(message, event)
                return

            # Only process text messages beyond here
            if message.message_type != "text":
                return

            # Only process personal (p2p) messages — skip group chat for now
            if message.chat_type != "p2p":
                return

            # Parse the text content
            raw_content = message.content or "{}"
            try:
                content_obj = json.loads(raw_content)
                text = content_obj.get("text", "")
            except (json.JSONDecodeError, TypeError):
                text = raw_content

            if not text:
                return

            # Extract sender info and remember for replies
            sender = event.sender
            sender_id_obj = sender.sender_id if sender else None
            open_id = sender_id_obj.open_id if sender_id_obj else ""
            if open_id:
                self._last_open_id = open_id

            logger.info(
                "Feishu message from %s: %s",
                open_id, text[:80],
            )

            # Wrap in our WxMessage type and forward to the command pipeline
            wx_msg = WxMessage(
                id=message.message_id or "",
                type=1,  # TEXT (same as WeChat)
                sender=open_id,
                roomid="",
                content=text,
                timestamp=int(message.create_time or "0"),
            )
            try:
                self._on_message(wx_msg)
            except Exception as e:
                logger.error("Error in message callback: %s", e)

        except Exception as e:
            logger.error("Error handling Feishu message: %s", e)

    def _handle_image_message(self, message, event) -> None:
        """Download an image message and forward as a file path to the pipeline."""
        try:
            raw_content = message.content or "{}"
            content_obj = json.loads(raw_content)
            image_key = content_obj.get("image_key", "")
            if not image_key:
                return

            # Download image from Feishu
            resp = self._api_client.im.v1.image.get(
                GetImageRequest.builder().image_key(image_key).build()
            )
            if not resp.success():
                logger.warning("Failed to download image: %s", resp.msg)
                return

            # Save to temp file
            suffix = ".jpg"
            resp_body = resp.data
            if hasattr(resp_body, 'file'):
                suffix = f".{resp_body.file.file_name.split('.')[-1]}" if resp_body.file.file_name else ".jpg"
                img_bytes = resp_body.file.data
                # data is a class with read()
                if hasattr(img_bytes, 'read'):
                    img_bytes = img_bytes.read()
                elif isinstance(img_bytes, bytes):
                    pass
                else:
                    img_bytes = base64.b64decode(img_bytes)
            else:
                # Fallback: raw bytes response
                img_bytes = resp

            if isinstance(img_bytes, str):
                img_bytes = img_bytes.encode()

            fd, path = tempfile.mkstemp(suffix=suffix, prefix="feishu_img_")
            with os.fdopen(fd, 'wb') as f:
                f.write(img_bytes)

            logger.info("Image saved to %s (%d bytes)", path, len(img_bytes))

            # Forward as a file path reference
            wx_msg = WxMessage(
                id=message.message_id or "",
                type=3,  # IMAGE type
                sender=event.sender.sender_id.open_id if event.sender and event.sender.sender_id else "",
                roomid="",
                content=f"[图片消息，已保存到: {path}]",
                timestamp=int(message.create_time or "0"),
            )
            wx_msg._image_path = path  # type: ignore[attr-defined]
            self._on_message(wx_msg)

        except Exception as e:
            logger.error("Error handling image: %s", e)

    # --- Send helpers --------------------------------------------------------

    def send_file(self, file_path: str, open_id: Optional[str] = None) -> None:
        """Upload a local file and send it to the user via Feishu."""
        if self._api_client is None:
            logger.error("Cannot send file: Feishu client not initialized")
            return

        target = open_id or self._last_open_id
        if not target or not os.path.exists(file_path):
            return

        try:
            file_name = os.path.basename(file_path)
            file_size = os.path.getsize(file_path)

            # Upload file to Feishu
            from lark_oapi.api.im.v1 import CreateFileRequest, CreateFileRequestBody
            f = open(file_path, 'rb')
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

            if not resp.success():
                logger.warning("File upload failed: %s", resp.msg)
                return

            file_key = resp.data.file_key
            logger.info("File uploaded: %s (%d bytes, key=%s)", file_name, file_size, file_key)

            # Send as message
            from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody
            msg_body = (
                CreateMessageRequestBody.builder()
                .msg_type("file")
                .content(json.dumps({"file_key": file_key}))
                .receive_id(target)
                .build()
            )
            msg_req = CreateMessageRequest.builder().receive_id_type("open_id").request_body(msg_body).build()
            self._api_client.im.v1.message.create(msg_req)

            logger.info("File sent: %s", file_name)
        except Exception as e:
            logger.error("Failed to send file: %s", e)

    def send_image(self, image_path: str, open_id: Optional[str] = None) -> None:
        """Upload and send an image via Feishu."""
        if self._api_client is None:
            return
        target = open_id or self._last_open_id
        if not target or not os.path.exists(image_path):
            logger.warning("send_image: no target or file not found (target=%s, path=%s)", target, image_path)
            return

        try:
            from lark_oapi.api.im.v1 import CreateImageRequest, CreateImageRequestBody
            f = open(image_path, 'rb')
            body = (
                CreateImageRequestBody.builder()
                .image_type("message")
                .image(f)
                .build()
            )
            request = CreateImageRequest.builder().request_body(body).build()
            resp = self._api_client.im.v1.image.create(request)
            f.close()

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
            msg_req = CreateMessageRequest.builder().receive_id_type("open_id").request_body(msg_body).build()
            self._api_client.im.v1.message.create(msg_req)

            logger.info("Image sent: %s", image_path)
        except Exception as e:
            logger.error("Failed to send image: %s", e)

    def send_text(self, text: str, open_id: Optional[str] = None) -> None:
        """Send a text message to a user by their *open_id*.

        If *open_id* is omitted, the bot replies to the user who last sent
        a message (tracked automatically).
        """
        if self._api_client is None:
            logger.error("Cannot send text: Feishu client not initialized")
            return

        target = open_id or self._last_open_id
        if not target:
            logger.warning("No target open_id available; cannot send Feishu message")
            return

        # Dedup: skip if exact same text was just sent (prevents API-level duplicates)
        if self._recent_texts and text == self._recent_texts[-1]:
            return
        self._recent_texts.append(text)
        self._recent_texts = self._recent_texts[-3:]  # keep only last 3

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

        try:
            resp = self._api_client.im.v1.message.create(request)
            if not resp.success():
                logger.warning(
                    "Feishu send failed: code=%d msg=%s",
                    resp.code, resp.msg,
                )
            else:
                logger.info("Feishu text sent: %s", text[:60])
        except Exception as e:
            logger.error("Failed to send Feishu text: %s", e)
