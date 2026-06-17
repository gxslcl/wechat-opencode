"""Result formatter — split output, heartbeats, and status messages."""

import logging
from typing import List

from wechat_opencode.config import Config
from wechat_opencode.types import ExecutionResult, FormattedPart

logger = logging.getLogger(__name__)


class ResultFormatter:
    """Formats opencode execution results for WeChat messages."""

    def __init__(self, config: Config) -> None:
        self._max_len = config.wechat.max_message_length
        self._max_parts = config.wechat.max_parts

    def format_result(self, result: ExecutionResult) -> List[FormattedPart]:
        """Split execution output into WeChat-sized parts."""
        text = result.output if result.success else f"Error: {result.error or 'unknown'}"
        if not text:
            text = "(no output)"

        raw_chunks = self._split_text(text)
        total = len(raw_chunks)

        parts = []
        for i, chunk in enumerate(raw_chunks):
            is_last = (i == total - 1)
            part_num = i + 1

            if total > 1:
                content = f"[{part_num}/{total}]\n{chunk}"
            else:
                content = chunk

            parts.append(FormattedPart(
                part_number=part_num,
                total_parts=total,
                content=content,
                is_last=is_last,
            ))

        return parts

    def format_heartbeat(self, elapsed_seconds: int) -> str:
        """Return a heartbeat message for long-running commands."""
        return f"\u23f3 \u6267\u884c\u4e2d... ({elapsed_seconds}s)"

    def format_error(self, error_msg: str) -> str:
        """Return an error message."""
        return f"\u274c \u9519\u8bef: {error_msg}"

    def format_start(self, command: str) -> str:
        """Return a start notification with estimated duration."""
        display = command[:50] + "..." if len(command) > 50 else command
        # Estimate duration based on content length
        length = len(command)
        if length > 1500:
            eta = "3-5分钟"
        elif length > 600:
            eta = "1-3分钟"
        elif length > 200:
            eta = "30-60秒"
        else:
            eta = "10-30秒"
        return f"\U0001f680 \u6267\u884c: {display}\n\u23f3 \u9884\u8ba1: {eta}"

    def format_timeout(self, command: str, timeout: int) -> str:
        """Return a timeout notification."""
        display = command[:30] + "..." if len(command) > 30 else command
        return f"\u23f0 \u8d85\u65f6: \u547d\u4ee4\u6267\u884c\u8d85\u8fc7 {timeout}s"

    def format_queued(self, position: int) -> str:
        """Return a queue position notification."""
        return f"\u23f3 \u6392\u961f\u4e2d\uff0c\u524d\u9762\u8fd8\u6709 {position} \u4e2a\u4efb\u52a1"

    def format_truncation_notice(self) -> str:
        """Return truncation notice for output too large even after splitting."""
        return "... \u8f93\u51fa\u8fc7\u957f\uff0c\u5b8c\u6574\u7ed3\u679c\u8bf7\u67e5\u770b\u672c\u5730\u65e5\u5fd7"

    def _split_text(self, text: str) -> List[str]:
        """Split text into chunks respecting newline boundaries."""
        if len(text) <= self._max_len:
            return [text]

        chunks: List[str] = []
        remaining = text

        while remaining and len(chunks) < self._max_parts:
            if len(remaining) <= self._max_len:
                chunks.append(remaining)
                break

            # Try to split at last newline before max_len
            split_pos = remaining.rfind("\n", 0, self._max_len)
            if split_pos == -1:
                # No newline found — hard split
                split_pos = self._max_len
            else:
                split_pos += 1  # Include the newline in current chunk

            chunks.append(remaining[:split_pos])
            remaining = remaining[split_pos:]

        if remaining:
            # Exceeded max_parts — add truncation notice to last chunk
            notice = self.format_truncation_notice()
            chunks[-1] = chunks[-1].rstrip() + "\n" + notice

        return chunks
