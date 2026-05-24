"""Tests for wechat_opencode.core."""

import time
from unittest.mock import MagicMock, patch

import pytest

from wechat_opencode.config import Config
from wechat_opencode.core import WeChatOpenCode
from wechat_opencode.types import WxMessage, Command, ExecutionResult


@pytest.fixture
def config():
    return Config()


@pytest.fixture
def app(config):
    return WeChatOpenCode(config, dry_run=True)


class TestWeChatOpenCodePipeline:
    def test_handle_message_routes_oc_command(self, app):
        msg = WxMessage(
            id="1", type=1, sender="filehelper",
            roomid="", content="/oc hello", timestamp=1700000000,
        )

        # Mock bot and queue
        app._bot = MagicMock()
        app._exec_queue = MagicMock()

        app._handle_message(msg)

        # Should have sent start notification
        app._bot.send_text.assert_called_once()
        # Should have submitted to queue
        app._exec_queue.submit.assert_called_once()
        # Command should contain the original content (possibly with context)
        cmd = app._exec_queue.submit.call_args[0][0]
        assert "hello" in cmd.content

    def test_handle_message_ignores_non_oc(self, app):
        msg = WxMessage(
            id="1", type=1, sender="filehelper",
            roomid="", content="just chatting", timestamp=1700000000,
        )

        app._bot = MagicMock()
        app._exec_queue = MagicMock()

        app._handle_message(msg)

        # Should not have called send_text or submit
        app._bot.send_text.assert_not_called()
        app._exec_queue.submit.assert_not_called()

    def test_handle_result_sends_parts(self, app):
        result = ExecutionResult(success=True, output="hello world")
        command = Command(
            original_message=WxMessage(
                id="1", type=1, sender="filehelper",
                roomid="", content="/oc hello", timestamp=1700000000,
            ),
            content="hello",
            timestamp=1700000000,
        )

        app._bot = MagicMock()
        app._handle_result(command, result)
        assert app._bot.send_text.call_count >= 1

    def test_handle_result_no_bridge(self, app):
        result = ExecutionResult(success=True, output="hello")
        command = Command(
            original_message=WxMessage(
                id="1", type=1, sender="filehelper",
                roomid="", content="/oc hello", timestamp=1700000000,
            ),
            content="hello",
            timestamp=1700000000,
        )

        app._bot = None
        app._handle_result(command, result)  # should not raise

    def test_oc_stop_triggers_restart(self, app):
        msg = WxMessage(
            id="1", type=1, sender="filehelper",
            roomid="", content="/oc stop", timestamp=1700000000,
        )

        app._bot = MagicMock()
        app._exec_queue = MagicMock()
        app._restart_services = MagicMock()

        app._handle_message(msg)

        app._bot.send_text.assert_called_once()
        app._restart_services.assert_called_once()
