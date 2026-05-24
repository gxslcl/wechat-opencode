"""Permission checker — detect dangerous operations before execution."""

import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Patterns that indicate dangerous operations (case-insensitive)
DANGEROUS_PATTERNS = [
    "rm ", "rm -rf", "rmdir", "rm -r",
    "del ", "delete ",
    "format ", "mkfs",
    "sudo ", "su ",
    "chmod 777",
    "> /dev/", "dd if=",
    "shutdown", "reboot",
    "DROP TABLE", "TRUNCATE",
    ":(){ :|:& };:",  # fork bomb
]


class PermissionChecker:
    """Checks commands for dangerous patterns before execution.

    When a dangerous command is detected, execution is deferred until the
    user explicitly confirms by replying ``YES``.
    """

    def __init__(self) -> None:
        self._pending_command = None  # stored when awaiting confirmation

    def check(self, command: str) -> Tuple[bool, str]:
        """Check if *command* looks dangerous.

        Returns ``(is_dangerous, reason)``.
        """
        cmd_lower = command.lower()
        for pattern in DANGEROUS_PATTERNS:
            if pattern.lower() in cmd_lower:
                return True, self._describe(pattern)
        return False, ""

    def set_pending(self, command_obj) -> None:
        """Store a command that is awaiting user confirmation."""
        self._pending_command = command_obj

    def get_pending(self):
        """Retrieve the pending command, clearing the slot.

        Returns ``None`` if no command is pending.
        """
        cmd = self._pending_command
        self._pending_command = None
        return cmd

    @property
    def has_pending(self) -> bool:
        """Whether there is a command awaiting confirmation."""
        return self._pending_command is not None

    # --- Internal -------------------------------------------------------------

    @staticmethod
    def _describe(pattern: str) -> str:
        """Return a human-readable description for a dangerous pattern."""
        descriptions = {
            "rm ":       "危险操作: 删除文件",
            "rm -rf":    "危险操作: 强制递归删除目录",
            "rmdir":     "危险操作: 删除目录",
            "rm -r":     "危险操作: 递归删除",
            "del ":      "危险操作: 删除文件",
            "delete ":   "危险操作: 删除操作",
            "format ":   "严重危险: 格式化磁盘",
            "mkfs":      "严重危险: 创建文件系统",
            "sudo ":     "危险操作: 超级用户权限",
            "su ":       "危险操作: 切换用户",
            "chmod 777": "危险操作: 开放全部权限",
            "> /dev/":   "危险操作: 写入设备文件",
            "dd if=":    "危险操作: 磁盘操作",
            "shutdown":  "危险操作: 关闭系统",
            "reboot":    "危险操作: 重启系统",
            "DROP TABLE":"数据库危险: 删除表",
            "TRUNCATE":  "数据库危险: 清空表",
        }
        return descriptions.get(pattern, f"危险操作: 匹配模式 '{pattern}'")
