"""Tests for wechat_opencode.router."""

import pytest

from wechat_opencode.config import Config
from wechat_opencode.router import MessageRouter
from wechat_opencode.types import WxMessage


@pytest.fixture
def router():
    return MessageRouter(Config())


def _make_msg(content: str) -> WxMessage:
    return WxMessage(
        id="1", type=1, sender="filehelper",
        roomid="", content=content, timestamp=1700000000,
    )


class TestMessageRouterRoute:
    def test_route_extracts_command(self, router):
        msg = _make_msg("/oc hello world")
        cmd = router.route(msg)
        assert cmd is not None
        assert cmd.content == "hello world"

    def test_route_returns_none_for_non_prefix(self, router):
        msg = _make_msg("hello world")
        assert router.route(msg) is None

    def test_route_returns_none_for_empty_command(self, router):
        msg = _make_msg("/oc")
        assert router.route(msg) is None

    def test_route_returns_none_for_prefix_only_whitespace(self, router):
        msg = _make_msg("/oc   ")
        assert router.route(msg) is None

    def test_route_case_insensitive(self, router):
        msg = _make_msg("/OC hello")
        cmd = router.route(msg)
        assert cmd is not None
        assert cmd.content == "hello"

    def test_route_preserves_original_message(self, router):
        msg = _make_msg("/oc test")
        cmd = router.route(msg)
        assert cmd.original_message is msg
        assert cmd.original_message.content == "/oc test"


class TestMessageRouterIsCommand:
    def test_is_command_with_prefix(self, router):
        msg = _make_msg("/oc hello")
        assert router.is_command(msg) is True

    def test_is_command_without_prefix(self, router):
        msg = _make_msg("hello")
        assert router.is_command(msg) is False

    def test_is_command_case_insensitive(self, router):
        msg = _make_msg("/OC hello")
        assert router.is_command(msg) is True


class TestMessageRouterExtractCommand:
    def test_extract_strips_prefix(self, router):
        msg = _make_msg("/oc write a test")
        assert router.extract_command(msg) == "write a test"

    def test_extract_with_extra_whitespace(self, router):
        msg = _make_msg("/oc   write a test")
        assert router.extract_command(msg) == "write a test"

    def test_extract_empty_after_prefix(self, router):
        msg = _make_msg("/oc")
        assert router.extract_command(msg) == ""
