"""Tests for wechat_opencode.types."""

from wechat_opencode.types import (
    Command,
    ExecutionResult,
    FormattedPart,
    MessageType,
    ServiceState,
    WxMessage,
    DEFAULT_PREFIX,
    MAX_MSG_LEN,
    MAX_PARTS,
)


class TestWxMessage:
    def test_create(self):
        msg = WxMessage(
            id="1", type=1, sender="filehelper",
            roomid="", content="hello", timestamp=0,
        )
        assert msg.id == "1"
        assert msg.type == 1
        assert msg.content == "hello"

    def test_frozen(self):
        msg = WxMessage(
            id="1", type=1, sender="filehelper",
            roomid="", content="hello", timestamp=0,
        )
        try:
            msg.content = "changed"
            assert False, "Should raise FrozenInstanceError"
        except AttributeError:
            pass


class TestCommand:
    def test_create(self):
        msg = WxMessage(
            id="1", type=1, sender="filehelper",
            roomid="", content="/oc hello", timestamp=100,
        )
        cmd = Command(original_message=msg, content="hello", timestamp=100)
        assert cmd.content == "hello"
        assert cmd.timestamp == 100


class TestExecutionResult:
    def test_success(self):
        result = ExecutionResult(success=True, output="done", duration_seconds=1.5)
        assert result.success is True
        assert result.output == "done"
        assert result.error is None

    def test_failure(self):
        result = ExecutionResult(
            success=False, output="", error="timeout", duration_seconds=300,
        )
        assert result.success is False
        assert result.error == "timeout"


class TestFormattedPart:
    def test_single_part(self):
        part = FormattedPart(part_number=1, total_parts=1, content="output", is_last=True)
        assert part.is_last is True
        assert part.total_parts == 1


class TestEnums:
    def test_service_states(self):
        assert ServiceState.STOPPED.value == "stopped"
        assert ServiceState.RUNNING.value == "running"

    def test_message_types(self):
        assert MessageType.TEXT == 1
        assert MessageType.IMAGE == 3


class TestConstants:
    def test_defaults(self):
        assert DEFAULT_PREFIX == "/oc"
        assert MAX_MSG_LEN == 4000
        assert MAX_PARTS == 10
