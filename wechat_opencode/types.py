"""Type definitions and constants for wechat_opencode."""

from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import List, Optional


# --- Enums ---

class ServiceState(Enum):
    """Service lifecycle states."""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"


class MessageType(IntEnum):
    """WeChat message types (matching wcferry type constants)."""
    TEXT = 1
    IMAGE = 3
    VOICE = 34
    VIDEO = 43
    OTHER = 99


# --- Constants ---

DEFAULT_PREFIX = "/oc"
MAX_MSG_LEN = 4000
MAX_PARTS = 10
DEFAULT_SERVE_PORT = 4096
DEFAULT_TIMEOUT = 300  # seconds
DEFAULT_HEARTBEAT_INTERVAL = 30  # seconds


# --- Data Classes ---

@dataclass(frozen=True)
class WxMessage:
    """A WeChat message (mirrors wcferry WxMsg fields)."""
    id: str
    type: int
    sender: str
    roomid: str
    content: str
    timestamp: int


@dataclass(frozen=True)
class Command:
    """A parsed command extracted from a /oc-prefixed WeChat message."""
    original_message: WxMessage
    content: str  # command text without the prefix
    timestamp: int
    session_id: Optional[str] = None  # None=continue last, "__new__"=fresh session


# --- Protocol tags for supervisor ↔ worker communication ---

TAG_TASK = "[TASK:"       # 监工 → 执行: 分配任务
TAG_PROGRESS = "[进度:"    # 执行 → 监工: 进度汇报
TAG_CONFIRM = "[确认:"     # 执行 → 用户: 需要确认
TAG_RESULT = "[结果:"      # 执行 → 监工: 任务完成
TAG_CANCEL = "[CANCEL]"   # 用户/监工 → Bridge: 取消
TAG_TIMEOUT = "[超时]"     # Bridge → 监工: 任务超时


# --- Worker state tracking ---

@dataclass
class WorkerState:
    """Tracks the state of the execution (worker) session."""
    session_id: str = ""
    task: str = ""
    status: str = "idle"  # idle, running, done
    started_at: float = 0.0
    updated_at: float = 0.0
    last_text: str = ""  # most recent text from the worker


@dataclass
class ExecutionResult:
    """Result of an opencode command execution."""
    success: bool
    output: str
    duration_seconds: float = 0.0
    session_id: str = ""
    error: Optional[str] = None


@dataclass(frozen=True)
class FormattedPart:
    """One part of a potentially multi-part formatted result."""
    part_number: int
    total_parts: int
    content: str
    is_last: bool


@dataclass
class FileCandidate:
    """A candidate file for transfer."""
    path: str
    name: str
    size: int = 0
    modified: float = 0.0
    similarity: float = 1.0


@dataclass
class FileSelectionState:
    """State when user needs to pick from file candidates."""
    candidates: List[FileCandidate] = field(default_factory=list)
    query: str = ""
    expired: bool = False
