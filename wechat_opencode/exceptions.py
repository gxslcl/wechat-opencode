"""Unified exception hierarchy for wechat_opencode."""

from typing import Optional


class WOCError(Exception):
    """Base exception for all wechat-opencode errors."""

    def __init__(
        self,
        message: str,
        *,
        inner: Optional[Exception] = None,
        recoverable: bool = True,
    ) -> None:
        super().__init__(message)
        self.inner = inner
        self.recoverable = recoverable


class BotError(WOCError):
    """Bot (WeChat/Feishu) connection or operation error."""


class ConfigError(WOCError):
    """Configuration loading or validation error."""


class SessionError(WOCError):
    """OpenCode session or serve error."""


class WorkerError(WOCError):
    """Worker execution or polling error."""


class PermissionDenied(WOCError):
    """User denied a permission-required operation."""


class ExecutionTimeout(WOCError):
    """Command or task execution timed out."""
