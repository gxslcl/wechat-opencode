"""Shared test fixtures for wechat_opencode tests."""

import pytest
from wechat_opencode.types import WxMessage


@pytest.fixture
def sample_text_message() -> WxMessage:
    """A text message from File Transfer Assistant."""
    return WxMessage(
        id="1234567890",
        type=1,
        sender="filehelper",
        roomid="",
        content="/oc hello world",
        timestamp=1700000000,
    )


@pytest.fixture
def sample_non_prefix_message() -> WxMessage:
    """A text message without /oc prefix."""
    return WxMessage(
        id="1234567891",
        type=1,
        sender="filehelper",
        roomid="",
        content="just a normal message",
        timestamp=1700000001,
    )


@pytest.fixture
def sample_image_message() -> WxMessage:
    """A non-text message (image)."""
    return WxMessage(
        id="1234567892",
        type=3,
        sender="filehelper",
        roomid="",
        content="<xml>image data</xml>",
        timestamp=1700000002,
    )


@pytest.fixture
def sample_group_message() -> WxMessage:
    """A message from a group chat (not filehelper)."""
    return WxMessage(
        id="1234567893",
        type=1,
        sender="someone@chatroom",
        roomid="12345678@chatroom",
        content="/oc hello",
        timestamp=1700000003,
    )
