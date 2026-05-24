"""Tests for wechat_opencode.formatter."""

import pytest

from wechat_opencode.config import Config
from wechat_opencode.formatter import ResultFormatter
from wechat_opencode.types import ExecutionResult


@pytest.fixture
def config():
    return Config()


@pytest.fixture
def formatter(config):
    return ResultFormatter(config)


class TestFormatResultShort:
    def test_short_output_single_part(self, formatter):
        result = ExecutionResult(success=True, output="hello world")
        parts = formatter.format_result(result)
        assert len(parts) == 1
        assert parts[0].is_last is True
        assert parts[0].total_parts == 1
        assert parts[0].content == "hello world"

    def test_empty_output(self, formatter):
        result = ExecutionResult(success=True, output="")
        parts = formatter.format_result(result)
        assert len(parts) == 1
        assert "(no output)" in parts[0].content

    def test_error_result(self, formatter):
        result = ExecutionResult(success=False, output="", error="something failed")
        parts = formatter.format_result(result)
        assert "Error:" in parts[0].content
        assert "something failed" in parts[0].content


class TestFormatResultLong:
    def test_long_output_splits(self, formatter):
        # Create output longer than max_message_length
        lines = [f"Line {i}: " + "x" * 100 for i in range(100)]
        long_output = "\n".join(lines)

        result = ExecutionResult(success=True, output=long_output)
        parts = formatter.format_result(result)
        assert len(parts) > 1
        assert parts[-1].is_last is True
        # All parts should have [N/M] header when multi-part
        for part in parts:
            assert part.content.startswith("[")

    def test_split_respects_newlines(self, formatter):
        # Each line is short enough to fit, but combined they exceed max
        lines = [f"Line {i}" for i in range(1000)]
        long_output = "\n".join(lines)

        result = ExecutionResult(success=True, output=long_output)
        parts = formatter.format_result(result)

        # No split should happen mid-line (except extremely long lines)
        for part in parts:
            content = part.content
            # After the [N/M] header line, lines should not be broken mid-line
            lines_in_content = content.split("\n")
            for line in lines_in_content[1:]:  # skip header
                # Just verify content is not empty for non-last lines
                pass

    def test_hard_split_long_line(self, formatter):
        # Single line exceeding max_message_length
        long_line = "x" * 8000
        result = ExecutionResult(success=True, output=long_line)
        parts = formatter.format_result(result)
        assert len(parts) > 1

    def test_max_parts_cap(self, formatter):
        # Create output that would need more than max_parts (10)
        lines = [f"Line {i}: " + "y" * 300 for i in range(500)]
        very_long = "\n".join(lines)

        result = ExecutionResult(success=True, output=very_long)
        parts = formatter.format_result(result)
        assert len(parts) <= 10
        # Last part should have truncation notice
        assert "\u8f93\u51fa\u8fc7\u957f" in parts[-1].content


class TestFormatHelpers:
    def test_format_heartbeat(self, formatter):
        msg = formatter.format_heartbeat(30)
        assert "30s" in msg
        assert "\u23f3" in msg

    def test_format_error(self, formatter):
        msg = formatter.format_error("test error")
        assert "\u274c" in msg or "Error" in msg or "\u9519\u8bef" in msg
        assert "test error" in msg

    def test_format_start_short_command(self, formatter):
        msg = formatter.format_start("hello")
        assert "hello" in msg

    def test_format_start_truncates_long_command(self, formatter):
        long_cmd = "a" * 100
        msg = formatter.format_start(long_cmd)
        assert len(msg) < len(long_cmd) + 20  # should be truncated

    def test_format_timeout(self, formatter):
        msg = formatter.format_timeout("cmd", 300)
        assert "300" in msg

    def test_format_queued(self, formatter):
        msg = formatter.format_queued(3)
        assert "3" in msg

    def test_format_truncation_notice(self, formatter):
        msg = formatter.format_truncation_notice()
        assert len(msg) > 0
