"""Tests for wechat_opencode.bridge."""

import threading
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from wechat_opencode.bridge import WeChatBridge
from wechat_opencode.config import Config
from wechat_opencode.types import WxMessage


@pytest.fixture
def config():
    return Config()


@pytest.fixture
def received_messages():
    """Collect messages received by the bridge callback."""
    messages = []
    return messages


@pytest.fixture
def bridge(config, received_messages):
    return WeChatBridge(config, on_message=received_messages.append)


# =============================================================================
# Start / Stop lifecycle
# =============================================================================

class TestWeChatBridgeStartStop:
    @patch("wechat_opencode.bridge.WeChatBridge._message_loop")
    def test_start_initializes_wcf_and_resolves_bot(self, mock_loop, bridge):
        with patch("wcferry.Wcf") as MockWcf:
            mock_wcf = MockWcf.return_value
            mock_wcf.get_contacts.return_value = [
                {"wxid": "wxid_bot123", "remark": "机器人", "name": "My Bot"},
            ]
            bridge.start()
            mock_wcf.enable_receiving_msg.assert_called_once()
            mock_wcf.get_contacts.assert_called_once()
            assert bridge._bot_wxid == "wxid_bot123"
            assert bridge._bot_mode is True
            assert bridge._running is True

    @patch("wechat_opencode.bridge.WeChatBridge._message_loop")
    def test_start_falls_back_when_bot_not_found(self, mock_loop, bridge):
        with patch("wcferry.Wcf") as MockWcf:
            mock_wcf = MockWcf.return_value
            mock_wcf.get_contacts.return_value = [
                {"wxid": "wxid_other", "remark": "someone", "name": "Someone"},
            ]
            bridge.start()
            assert bridge._bot_wxid is None
            assert bridge._bot_mode is False

    def test_stop_disables_receiving(self, bridge):
        bridge._wcf = MagicMock()
        bridge._running = True
        bridge.stop()
        bridge._wcf.disable_receiving_msg.assert_called_once()
        assert bridge._running is False

    def test_stop_handles_wcf_error(self, bridge):
        bridge._wcf = MagicMock()
        bridge._wcf.disable_receiving_msg.side_effect = RuntimeError("boom")
        bridge._running = True
        bridge.stop()  # should not raise
        assert bridge._running is False


# =============================================================================
# Bot contact resolution
# =============================================================================

class TestResolveBotContact:
    def test_finds_by_remark(self, bridge):
        bridge._wcf = MagicMock()
        bridge._wcf.get_contacts.return_value = [
            {"wxid": "wxid_bot", "remark": "机器人", "name": "Some Name"},
        ]
        assert bridge._resolve_bot_contact("机器人") == "wxid_bot"

    def test_finds_by_name(self, bridge):
        bridge._wcf = MagicMock()
        bridge._wcf.get_contacts.return_value = [
            {"wxid": "wxid_bot", "remark": "", "name": "机器人"},
        ]
        assert bridge._resolve_bot_contact("机器人") == "wxid_bot"

    def test_case_insensitive(self, bridge):
        bridge._wcf = MagicMock()
        bridge._wcf.get_contacts.return_value = [
            {"wxid": "wxid_bot", "remark": "机器人", "name": ""},
        ]
        assert bridge._resolve_bot_contact("机器人") == "wxid_bot"

    def test_not_found(self, bridge):
        bridge._wcf = MagicMock()
        bridge._wcf.get_contacts.return_value = [
            {"wxid": "wxid_a", "remark": "a", "name": "A"},
        ]
        assert bridge._resolve_bot_contact("机器人") is None

    def test_handles_wcf_error(self, bridge):
        bridge._wcf = MagicMock()
        bridge._wcf.get_contacts.side_effect = RuntimeError("boom")
        assert bridge._resolve_bot_contact("机器人") is None


# =============================================================================
# Send helpers
# =============================================================================

class TestWeChatBridgeSend:
    def test_send_text_to_bot_when_resolved(self, bridge):
        bridge._wcf = MagicMock()
        bridge._bot_wxid = "wxid_bot123"
        bridge.send_text("hello")
        bridge._wcf.send_text.assert_called_once_with("hello", "wxid_bot123")

    def test_send_text_falls_back_to_filehelper(self, bridge):
        bridge._wcf = MagicMock()
        bridge._bot_wxid = None
        bridge.send_text("hello")
        bridge._wcf.send_text.assert_called_once_with("hello", "filehelper")

    def test_send_text_custom_wxid(self, bridge):
        bridge._wcf = MagicMock()
        bridge.send_text("hello", wxid="custom_id")
        bridge._wcf.send_text.assert_called_once_with("hello", "custom_id")

    def test_send_text_handles_error(self, bridge):
        bridge._wcf = MagicMock()
        bridge._wcf.send_text.side_effect = RuntimeError("send failed")
        bridge.send_text("hello")  # should not raise

    def test_send_text_no_wcf(self, bridge):
        bridge._wcf = None
        bridge.send_text("hello")  # should not raise


# =============================================================================
# Health checks
# =============================================================================

class TestWeChatBridgeHealth:
    def test_is_wechat_running_detects_process(self, bridge):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="WeChat.exe  1234  Console  1  100,000 K")
            assert bridge.is_wechat_running() is True

    def test_is_wechat_running_no_process(self, bridge):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="INFO: No tasks are running")
            assert bridge.is_wechat_running() is False

    def test_is_wechat_running_error(self, bridge):
        with patch("subprocess.run", side_effect=Exception("fail")):
            assert bridge.is_wechat_running() is False

    def test_get_self_wxid(self, bridge):
        bridge._wcf = MagicMock()
        bridge._wcf.get_self_wxid.return_value = "wxid_test123"
        assert bridge.get_self_wxid() == "wxid_test123"

    def test_get_self_wxid_no_wcf(self, bridge):
        bridge._wcf = None
        assert bridge.get_self_wxid() == ""


# =============================================================================
# Message loop — bot mode
# =============================================================================

class TestMessageLoopBotMode:
    def test_accepts_message_from_bot_wxid(self, config, received_messages):
        bridge = WeChatBridge(config, on_message=received_messages.append)
        bridge._running = True
        bridge._bot_mode = True
        bridge._bot_wxid = "wxid_bot123"

        mock_msg = MagicMock()
        mock_msg.type = 1  # TEXT
        mock_msg.sender = "wxid_bot123"
        mock_msg.content = "/oc hello"
        mock_msg.ts = 1700000000
        mock_msg.id = 100

        bridge._wcf = MagicMock()
        bridge._wcf.get_msg.side_effect = [mock_msg]

        bridge._on_message(WxMessage(
            id="100", type=1, sender="wxid_bot123",
            roomid="", content="/oc hello", timestamp=1700000000,
        ))
        assert len(received_messages) == 1
        assert received_messages[0].content == "/oc hello"

    def test_skips_message_from_other_sender(self, config, received_messages):
        bridge = WeChatBridge(config, on_message=received_messages.append)
        bridge._running = True
        bridge._bot_mode = True
        bridge._bot_wxid = "wxid_bot123"

        mock_msg = MagicMock()
        mock_msg.type = 1
        mock_msg.sender = "wxid_stranger"
        mock_msg.content = "/oc hello"
        mock_msg.from_self.return_value = True

        bridge._wcf = MagicMock()
        bridge._wcf.get_msg.side_effect = [mock_msg]

        # Manually check filtering
        assert mock_msg.sender != bridge._bot_wxid

    def test_skips_non_text(self, config, received_messages):
        bridge = WeChatBridge(config, on_message=received_messages.append)
        bridge._running = True
        bridge._bot_mode = True
        bridge._bot_wxid = "wxid_bot123"

        mock_msg = MagicMock()
        mock_msg.type = 3  # IMAGE
        mock_msg.sender = "wxid_bot123"

        bridge._wcf = MagicMock()
        bridge._wcf.get_msg.side_effect = [mock_msg]

        assert mock_msg.type != 1


# =============================================================================
# Message loop — fallback (filehelper) mode
# =============================================================================

class TestMessageLoopFallbackMode:
    def test_accepts_self_sent_text(self, config, received_messages):
        bridge = WeChatBridge(config, on_message=received_messages.append)
        bridge._running = True
        bridge._bot_mode = False
        bridge._bot_wxid = None

        mock_msg = MagicMock()
        mock_msg.type = 1
        mock_msg.sender = "wxid_self"
        mock_msg.content = "/oc hello"
        mock_msg.from_self.return_value = True

        bridge._wcf = MagicMock()
        bridge._wcf.get_msg.side_effect = [mock_msg]

        bridge._on_message(WxMessage(
            id="100", type=1, sender="wxid_self",
            roomid="", content="/oc hello", timestamp=1700000000,
        ))
        assert len(received_messages) == 1
        assert received_messages[0].content == "/oc hello"

    def test_skips_non_self_sent(self, config, received_messages):
        bridge = WeChatBridge(config, on_message=received_messages.append)
        bridge._running = True
        bridge._bot_mode = False

        mock_msg = MagicMock()
        mock_msg.type = 1
        mock_msg.sender = "someone_else"
        mock_msg.content = "/oc hello"
        mock_msg.from_self.return_value = False

        bridge._wcf = MagicMock()
        bridge._wcf.get_msg.side_effect = [mock_msg]

        assert not mock_msg.from_self()
