"""Main application loop — glues all modules together."""

import logging
import os
import re
import threading
import time
from typing import Optional, Union

from wechat_opencode.auto_reload import AutoReloader
from wechat_opencode.bus import MessageBus
from wechat_opencode.bridge import WeChatBridge
from wechat_opencode.config import BotType, Config
from wechat_opencode.context import ContextInjector
from wechat_opencode.cost_tracker import CostTracker
from wechat_opencode.feishu_bot import FeishuBot
from wechat_opencode.formatter import ResultFormatter
from wechat_opencode.git_diff import GitDiff
from wechat_opencode.health import HealthMonitor
from wechat_opencode.intent_router import analyze as analyze_intent, extract_artifacts
from wechat_opencode.permission import PermissionChecker
from wechat_opencode.ppt_designer import get_designer_prompt
from wechat_opencode.queue import ExecutionQueue
from wechat_opencode.router import MessageRouter
from wechat_opencode.screenshot import capture_desktop
from wechat_opencode.session import OpenCodeSession
from wechat_opencode.shutdown import ShutdownHandler
from wechat_opencode.task_tracker import TaskTracker
from wechat_opencode.types import (
    Command, ExecutionResult, WxMessage,
    TAG_CANCEL, TAG_CONFIRM, TAG_TASK,
)
from wechat_opencode.undo import UndoManager
from wechat_opencode.web_ui import start_server
from wechat_opencode.window_manager import (
    focus_window, focus_window_by_index, show_desktop,
    minimize_current, maximize_current, list_apps,
    open_app_or_file, open_by_index,
)
from wechat_opencode.worker import WorkerManager
from wechat_opencode.types import Command, ExecutionResult, WxMessage

logger = logging.getLogger(__name__)

# A bot can be either WeChatBridge or FeishuBot — both expose start/stop/send_text
Bot = Union[WeChatBridge, FeishuBot]


# --- Command registry for abbreviation resolution ---
# (primary_name, [aliases], description)
_CMD_SPEC = [
    ("stop",      [],                      "重启服务"),
    ("restart",   [],                      "重启服务"),
    ("new",       ["fresh"],               "新建执行会话"),
    ("help",      ["h"],                   "查看帮助"),
    ("cost",      [],                      "查看费用统计"),
    ("model",     [],                      "查看/切换模型"),
    ("screen",    ["screenshot"],          "截取电脑桌面"),
    ("ppt",       [],                      "生成PPT"),
    ("undo",      [],                      "撤销操作"),
    ("cancel",    [],                      "取消任务"),
    ("status",    [],                      "查看状态"),
    ("progress",  [],                      "进度报告间隔"),
    ("plan",      [],                      "规划并执行"),
    ("sessions",  ["list", "session"],     "会话列表"),
    ("tasks",     [],                      "任务列表"),
    ("task",      [],                      "任务详情"),
    ("cleartasks",[],                      "清空任务记录"),
    ("compact",   [],                      "压缩对话上下文"),
    ("file",      [],                      "文件传递"),
    ("focus",     [],                      "切换窗口到前台"),
    ("desktop",   [],                      "显示桌面"),
    ("min",       [],                      "最小化当前窗口"),
    ("max",       [],                      "最大化当前窗口"),
    ("apps",      [],                      "列出运行中的应用"),
    ("open",      [],                      "打开应用或文件"),
]

# Build lookup maps
_CMD_ALL: set = set()
_CMD_PRIMARY: dict = {}   # alias → primary_name
_CMD_DESC: dict = {}      # primary_name → description
for _primary, _aliases, _desc in _CMD_SPEC:
    _CMD_PRIMARY[_primary] = _primary
    _CMD_DESC[_primary] = _desc
    _CMD_ALL.add(_primary)
    for _a in _aliases:
        _CMD_PRIMARY[_a] = _primary
        _CMD_ALL.add(_a)


class WeChatOpenCode:
    """Main application — bridges messages (WeChat or Feishu) to opencode execution."""

    def __init__(self, config: Config, dry_run: bool = False) -> None:
        self._config = config
        self._dry_run = dry_run

        self._formatter = ResultFormatter(config)
        self._router = MessageRouter(config)
        # Supervisor session — runs with --pure (no MCP), never restarts
        self._session = OpenCodeSession(config)
        # Worker session — runs with full config (MCP/skills), can restart independently
        self._worker_session = OpenCodeSession(
            config, serve_port=config.opencode.worker_serve_port,
        )
        self._shutdown = ShutdownHandler()
        self._tracker = TaskTracker()
        self._context = ContextInjector(config)
        self._permission = PermissionChecker()
        self._costs = CostTracker()
        self._git = GitDiff(config.opencode.project_dir)
        self._undo = UndoManager(config.opencode.project_dir)
        self._reloader = AutoReloader(
            watch_dir=os.path.dirname(__file__),
            on_change=self._shutdown.trigger_shutdown,
            interval=3,
            is_busy=self._is_worker_busy,
        )

        # Message bus — all messages (incoming/outgoing) flow through here
        self._bus = MessageBus()
        self._bus.subscribe("incoming", self._on_bus_incoming)

        # Bot, queue, and health monitor initialized in start()
        self._bot: Optional[Bot] = None
        self._exec_queue: Optional[ExecutionQueue] = None
        self._health_monitor: Optional[HealthMonitor] = None

        # Session tracking
        self._supervisor_id: Optional[str] = None  # main chat session
        self._current_task_id: Optional[str] = None
        self._worker: Optional[WorkerManager] = None
        self._confirm_pending: bool = False
        self._cmd_selection: Optional[tuple] = None  # (primary_names: list, original_args: str)
        self._focus_query: Optional[str] = None  # pending focus query for candidate selection
        self._open_query: Optional[str] = None  # pending open query
        self._open_candidates: Optional[list] = None  # candidates for open selection
        self._seen_ids: set = set()
        self._worker_history: list = []  # [(title, session_id, status)]
        self._selected_worker_sid: Optional[str] = None
        self._last_cancelled_raw: Optional[str] = None  # for preemption context
        # Context compaction — idle-based
        self._last_active_time: float = time.time()
        self._last_compact_time: float = 0.0
        self._COMPACT_IDLE_SECONDS: int = 3600       # 1h idle before checking
        self._COMPACT_COOLDOWN: int = 3600           # 1h cooldown after compact
        self._COMPACT_MESSAGE_LIMIT: int = 300       # 300+ messages to trigger

    def start(self) -> None:
        """Start all components and enter main loop."""
        self._setup_logging()

        logger.info("Starting WeChat-OpenCode bridge...")
        self._shutdown.register(self.stop)

        # Start opencode serve — supervisor (no --pure, safe separation via ports)
        if not self._dry_run:
            try:
                url = self._session.start_serve()
                logger.info("Supervisor serve running at %s", url)
            except RuntimeError as e:
                logger.error("Failed to start supervisor serve: %s", e)
                return
        else:
            logger.info("Dry-run mode: skipping opencode serve start")

        # Start worker serve (full config, MCP/skills, separate port)
        if not self._dry_run:
            try:
                worker_url = self._worker_session.start_serve()
                logger.info("Worker serve running at %s", worker_url)
            except RuntimeError as e:
                logger.error("Failed to start worker serve: %s", e)
                # Non-fatal: worker tasks will fail but supervisor still works
        else:
            logger.info("Dry-run mode: skipping worker serve start")

        # Initialize queue (shared by both WeChat and Feishu)
        self._exec_queue = ExecutionQueue(
            session=self._session,
            config=self._config,
            on_result=self._handle_result,
            on_queued=self._handle_queued,
        )
        self._exec_queue.start()

        # Initialize bot based on config
        if self._config.bot_type == BotType.FEISHU:
            self._start_feishu()
        else:
            self._start_wechat()

        # Create supervisor session (the main chat session)
        self._init_supervisor()

        # Start auto-reloader (watches .py files for changes → auto-restart)
        self._reloader.start()

        # Start background context compaction monitor
        self._start_compact_monitor()

        # Block until shutdown (both modes run their bot in background threads)
        self._wait_for_shutdown()

    def _init_supervisor(self) -> None:
        """Create the supervisor session with system prompt.

        If ``_supervisor_id`` already exists and is alive, reuse it.
        """
        if self._supervisor_id:
            try:
                status = self._session.get_session_status(self._supervisor_id)
                if status.get("status") == "active":
                    logger.info("Reusing existing supervisor session: %s", self._supervisor_id)
                    return
            except Exception:
                pass
            logger.info("Supervisor session %s is stale; creating new one", self._supervisor_id)

        self._supervisor_id = self._session.create_session("监工")
        if not self._supervisor_id:
            logger.warning("Failed to create supervisor session")
            return

        # Initialize worker manager (uses separate worker serve for MCP/skills)
        self._worker = WorkerManager(
            session=self._worker_session,
            supervisor_id=self._supervisor_id,
            on_inject=self._inject_to_supervisor,
            on_notify=lambda msg: self._bot.send_text(msg) if self._bot else None,
            on_confirm=lambda wm: setattr(self, "_confirm_pending", True),
            on_finish=self._on_worker_finish,
            on_rollback=lambda: self._undo.restore_last(keep=True),
        )

        # Send supervisor system prompt (blocking — must finish before user messages)
        sys_prompt = (
            "你是监工。你和用户聊天、理解需求、分配任务。不亲自执行。\n\n"
            "规则：\n"
            "1. 用户有需要执行的任务 → 回复 [TASK: 任务目标]\n"
            "2. [进度: ...] → 告诉用户（如果含步骤信息如'步骤2/5'也一并转发）\n"
            "3. [结果: ...] → 告诉用户完成\n"
            "4. [确认: ...] → 转给用户，等回复后转发\n"
            "5. [结果: 失败 ...] → 分析失败原因\n"
            "   - 如果是可修复的问题 → [TASK: 修复XX问题]\n"
            "   - 如果无法修复 → 问用户是否换个方案\n"
            "6. 聊天直接回复，不发 TASK\n"
            "7. 取消 → [CANCEL]\n\n"
            "你是传话人。友好但简洁。主动帮用户想方案。"
        )
        self._session.execute(sys_prompt, session_id=self._supervisor_id, timeout=30)
        logger.info("Supervisor session created: %s", self._supervisor_id)

        # Start Web UI
        start_server(
            session=self._session,
            supervisor_id=self._supervisor_id,
            worker_status_fn=self._get_worker_info,
            tasks_fn=lambda: [f"{t.goal[:40]}" for t in self._tracker.list_recent(5)],
            costs_fn=lambda: f"${self._costs.summary.total_cost:.4f} ({self._costs.summary.total_commands}次)",
            model_fn=self._get_current_model,
            queue=self._exec_queue,
            bus=self._bus,
        )

    def _inject_to_supervisor(self, text: str) -> None:
        """Inject a status update into the supervisor session."""
        if not self._supervisor_id or not self._exec_queue:
            return
        cmd = Command(
            original_message=WxMessage(
                id="system", type=1, sender="worker", roomid="",
                content=text, timestamp=int(time.time()),
            ),
            content=text,
            timestamp=int(time.time()),
            session_id=self._supervisor_id,
        )
        self._exec_queue.submit(cmd)

    def _on_worker_finish(self, session_id: str, success: bool) -> None:
        """Callback from WorkerManager when a task finishes."""
        for h in self._worker_history:
            if h.get("session_id") == session_id:
                h["status"] = "done" if success else "failed"
                break

    def _start_ppt_task(self, topic: str, save_dir: Optional[str] = None) -> None:
        """Start a PPT designer worker with specialized prompt.

        Args:
            topic: PPT topic.
            save_dir: Directory to save the generated file. Defaults to Desktop.
        """
        if not self._worker or not self._bot:
            return
        self._worker.cancel()
        self._selected_worker_sid = None
        # PPT tasks are long-running — show progress every 30 s
        self._worker.set_progress_interval(30)

        if self._worker.start_with_prompt(topic, get_designer_prompt(save_dir=save_dir)):
            self._worker_history.append({
                "session_id": self._worker.worker.session_id,
                "task": topic, "status": "running",
            })
            self._bot.send_text(  # type: ignore[union-attr]
                f"🎨 PPT 设计师已就位\n"
                f"主题: {topic}\n设计师会先确认参数"
            )
        else:
            self._bot.send_text("❌ PPT 设计任务启动失败")  # type: ignore[union-attr]

    def _get_current_model(self) -> str:
        """Read current model from opencode.json."""
        try:
            import json
            with open("opencode.json", "r") as f:
                cfg = json.load(f)
            return cfg.get("model", "unknown")
        except Exception:
            return "unknown"

    def _is_worker_busy(self) -> bool:
        """Check if worker is currently executing a task."""
        return (
            self._worker is not None
            and self._worker.is_running
        )

    def _get_worker_info(self) -> dict:
        """Return current worker status for the Web UI."""
        if self._worker and self._worker.worker.status == "running":
            w = self._worker.worker
            return {"status": "running", "task": w.task, "started_at": w.started_at}
        return {"status": "idle"}

    def _switch_model(self, name: str) -> None:
        """Switch model in opencode.json and recreate supervisor."""
        models = {
            "flash": "deepseek/deepseek-chat",
            "pro": "deepseek/deepseek-v4-pro",
        }
        m = models.get(name.lower())
        if not m:
            self._bot.send_text(f"未知模型: {name}。可用: /model flash, /model pro")  # type: ignore[union-attr]
            return

        # Update opencode.json
        try:
            import json
            with open("opencode.json", "r") as f:
                cfg = json.load(f)
            cfg["model"] = m
            with open("opencode.json", "w") as f:
                json.dump(cfg, f, ensure_ascii=False)
        except Exception as e:
            self._bot.send_text(f"❌ 更新配置失败: {e}")  # type: ignore[union-attr]
            return

        # Model is read per-request from opencode.json by the LLM — no session restart needed
        self._bot.send_text(f"✅ 已切换到: {m}")  # type: ignore[union-attr]

    def _start_feishu(self) -> None:
        """Initialize and start the Feishu bot."""
        cfg = self._config.feishu
        if not cfg.app_id or not cfg.app_secret:
            logger.error("Feishu app_id and app_secret must be set in config")
            self.stop()
            return

        self._bot = FeishuBot(
            app_id=cfg.app_id,
            app_secret=cfg.app_secret,
            on_message=self._handle_message,
        )
        self._bot.set_bus(self._bus)

        if not self._dry_run:
            try:
                self._bot.start()
            except Exception as e:
                logger.error("Failed to start Feishu bot: %s", e)
                self.stop()
                return
        else:
            logger.info("Dry-run mode: skipping Feishu bot start")

        logger.info("Feishu bot is running")

    def _start_wechat(self) -> None:
        """Initialize and start the WeChat bridge."""
        # Initialize bridge
        self._bot = WeChatBridge(self._config, on_message=self._handle_message)

        # Start WeChat bridge
        if not self._dry_run:
            try:
                self._bot.start()
            except Exception as e:
                logger.error("Failed to start WeChat bridge: %s", e)
                self.stop()
                return
        else:
            logger.info("Dry-run mode: skipping WeChat bridge start")

        # Start health monitor (WeChat-only: monitors WeChat.exe + opencode serve)
        self._health_monitor = HealthMonitor(
            config=self._config,
            bridge=self._bot,
            session=self._session,
            shutdown_event=self._shutdown.shutdown_event,
            on_notify=self._bot.send_text if self._bot else None,
        )
        self._health_monitor.start()

        logger.info("WeChat bridge is running (prefix: %s)", self._config.wechat.prefix)

    def _wait_for_shutdown(self) -> None:
        """Block until a shutdown signal is received."""
        try:
            self._shutdown.shutdown_event.wait()
        except KeyboardInterrupt:
            pass
        self.stop()

    def stop(self) -> None:
        """Stop all components gracefully."""
        logger.info("Shutting down...")

        if self._health_monitor is not None:
            self._health_monitor.stop()
            self._health_monitor = None

        if self._exec_queue is not None:
            self._exec_queue.stop()
            self._exec_queue = None

        if self._bot is not None:
            self._bot.stop()
            self._bot = None

        if not self._dry_run:
            self._session.stop_serve()
            self._worker_session.stop_serve()

        logger.info("Shutdown complete.")

    def _restart_services(self) -> None:
        """Restart bot, queue, supervisor without exiting the process."""
        logger.info("Restarting services...")

        # Stop current bot
        if self._bot is not None:
            try:
                self._bot.stop()
            except Exception:
                pass
            self._bot = None

        # Stop queue
        if self._exec_queue is not None:
            self._exec_queue.stop()
            self._exec_queue = None

        # Restart queue
        self._exec_queue = ExecutionQueue(
            session=self._session,
            config=self._config,
            on_result=self._handle_result,
            on_queued=self._handle_queued,
        )
        self._exec_queue.start()

        # Restart bot
        if self._config.bot_type == BotType.FEISHU:
            self._start_feishu()
        else:
            self._start_wechat()

        # Re-send system prompt to existing supervisor session (don't recreate)
        if self._supervisor_id:
            sys_prompt = (
                "你是监工。你和用户聊天、理解需求、分配任务。不亲自执行。\n\n"
                "规则：\n"
                "1. 用户有需要执行的任务 → 回复 [TASK: 任务目标]\n"
                "2. [进度: ...] → 告诉用户（如果含步骤信息如'步骤2/5'也一并转发）\n"
                "3. [结果: ...] → 告诉用户完成\n"
                "4. [确认: ...] → 转给用户，等回复后转发\n"
                "5. [结果: 失败 ...] → 分析失败原因\n"
                "   - 如果是可修复的问题 → [TASK: 修复XX问题]\n"
                "   - 如果无法修复 → 问用户是否换个方案\n"
                "6. 聊天直接回复，不发 TASK\n"
                "7. 取消 → [CANCEL]\n\n"
                "你是传话人。友好但简洁。主动帮用户想方案。"
            )
            self._session.execute(sys_prompt, session_id=self._supervisor_id, timeout=30)
        else:
            self._init_supervisor()

        if self._bot:
            self._bot.send_text("✅ 服务已重启")  # type: ignore[union-attr]
        logger.info("Services restarted")

    def _update_active_time(self) -> None:
        """Mark user activity for idle-based compact."""
        self._last_active_time = time.time()

    def _on_bus_incoming(self, bus_msg: dict) -> None:
        """Callback from MessageBus when a user message arrives.

        Wraps bus message into WxMessage and routes through the existing
        _handle_message pipeline.  Synchronises the Feishu bot's
        ``_last_open_id`` so replies find the right target.
        """
        sender = bus_msg.get("sender", "")
        if sender and self._bot and hasattr(self._bot, "_last_open_id"):
            self._bot._last_open_id = sender  # type: ignore[union-attr]

        self._update_active_time()

        wx_msg = WxMessage(
            id=bus_msg.get("id", ""),
            type=1,
            sender=sender,
            roomid="",
            content=bus_msg.get("text", ""),
            timestamp=int(bus_msg.get("timestamp", time.time())),
        )
        self._handle_message(wx_msg)

    def _handle_message(self, message: WxMessage) -> None:
        """Callback from bot — fast ACK for Feishu's 3s timeout, then async processing."""

        # --- Synchronous: Dedup (Feishu may redeliver) ---
        if not hasattr(self, "_seen_ids"):
            self._seen_ids = set()
        if message.id:
            if message.id in self._seen_ids:
                return
            self._seen_ids.add(message.id)
            if len(self._seen_ids) > 2000:
                self._seen_ids.clear()

        # --- Synchronous: Route / extract raw content ---
        if self._config.bot_type == BotType.FEISHU:
            raw_content = message.content.strip()
        else:
            cmd = self._router.route(message)
            if cmd is None:
                return
            raw_content = cmd.content

        logger.info("ACK received: %s", raw_content[:60])

        # --- Synchronous: Interactive state transitions (fast, no LLM) ---

        # Command selection pending (abbreviation ambiguous)
        if self._cmd_selection is not None:
            if self._handle_cmd_selection(raw_content):
                return

        # Focus candidate selection pending
        if self._focus_query is not None:
            if self._handle_focus_selection(raw_content):
                return

        # Open candidate selection pending
        if self._open_query is not None and self._open_candidates is not None:
            if self._handle_open_selection(raw_content):
                return

        # Worker confirmation pending
        if self._worker and self._worker.is_running and self._confirm_pending:
            self._confirm_pending = False
            self._session.execute_async(
                f"用户选择: {raw_content}",
                session_id=self._worker.worker.session_id,
            )
            if self._bot:
                self._bot.send_text(f"✅ 已转发确认: {raw_content}")
            return

        # Permission check pending (user replying YES/NO)
        if self._permission.has_pending:
            response = raw_content.upper()
            if response == "YES":
                pending = self._permission.get_pending()
                if pending and self._bot:
                    self._bot.send_text("✅ 已批准，正在执行...")
                    self._submit_command(pending)
                return
            else:
                self._permission.get_pending()
                if self._bot:
                    self._bot.send_text("❌ 已取消危险操作")
                return

        # --- Asynchronous: Queue for background processing (prevents Feishu re-delivery) ---
        self._queue_incoming(message, raw_content)

    def _queue_incoming(self, message: WxMessage, raw_content: str) -> None:
        """Cancel pending async processing and start a new one.

        Implements the preemption pattern: a new inbound message cancels
        processing of the previous one, ensuring only the latest message
        is handled at any time.
        """
        # Cancel previous processing (if any) and save its content for context
        if hasattr(self, "_incoming_cancel") and self._incoming_cancel is not None:
            if hasattr(self, '_current_raw'):
                self._last_cancelled_raw = self._current_raw
            self._incoming_cancel.set()
            logger.info("Cancelled previous incoming processing (newer message arrived)")

        # Create fresh cancellation token
        self._incoming_cancel = threading.Event()

        logger.info("Queuing incoming message for async processing: %s", raw_content[:60])
        t = threading.Thread(
            target=self._process_incoming,
            args=(message, raw_content, self._incoming_cancel),
            daemon=True,
        )
        t.start()

    def _process_incoming(
        self, message: WxMessage, raw_content: str, cancel: threading.Event,
    ) -> None:
        """Background worker: process a single inbound message.

        Contains the routing logic previously in _handle_message:
        meta-commands, intent analysis, LLM fallback.
        Checks the *cancel* event before slow operations so a newer
        message can preempt this one.
        """
        # Store current raw content for preemption context (before cancel check)
        self._current_raw = raw_content

        if cancel.is_set():
            logger.info("Processing cancelled before start: %s", raw_content[:60])
            return

        # Save cancelled message context for _submit_command (NOT for intent analysis)
        self._preempt_context = self._last_cancelled_raw if self._last_cancelled_raw else None
        self._last_cancelled_raw = None

        logger.info("Processing started: %s", raw_content[:60])

        # --- Meta-commands (start with /) ---
        if raw_content.startswith("/"):
            if self._handle_meta_command(raw_content):
                logger.info("Processing completed (meta-command): %s", raw_content[:60])
                return

        # Stop command (WeChat mode, no / prefix)
        if raw_content.lower() == "stop":
            if cancel.is_set():
                return
            logger.info("Received stop command")
            if self._bot:
                self._bot.send_text("🔄 正在重启服务...")  # type: ignore[union-attr]
            self._restart_services()
            logger.info("Processing completed (stop): %s", raw_content[:60])
            return

        # --- Permission check for dangerous commands ---
        if cancel.is_set():
            return
        is_danger, reason = self._permission.check(raw_content)
        if is_danger and self._bot:
            self._bot.send_text(f"⚠️ {reason}")
            self._bot.send_text(
                f"命令: {raw_content[:100]}...\n"
                "回复 YES 批准执行 / 其他任意回复取消"
            )
            cmd = Command(
                original_message=message,
                content=raw_content,
                timestamp=message.timestamp,
                session_id=self._supervisor_id,
            )
            self._permission.set_pending(cmd)
            logger.info("Processing completed (permission required): %s", raw_content[:60])
            return

        # --- Intent Analysis: try built-in commands before LLM ---
        if cancel.is_set():
            return
        intent = analyze_intent(raw_content, session=self._session)
        if intent.type == "command" and intent.command:
            self._execute_intent_command(intent, message)
            logger.info("Processing completed (intent command): %s", raw_content[:60])
            return
        if intent.type == "compound" and intent.steps:
            self._execute_compound_intent(intent, message)
            logger.info("Processing completed (compound intent): %s", raw_content[:60])
            return

        # --- Regular opencode command (LLM fallback) ---
        if cancel.is_set():
            return
        self._submit_command(
            Command(
                original_message=message,
                content=raw_content,
                timestamp=message.timestamp,
                session_id=self._supervisor_id,
            )
        )
        logger.info("Processing completed (LLM fallback): %s", raw_content[:60])

    def _submit_command(self, command: Command) -> None:
        """Inject context, start tracking, and submit to queue."""
        if self._bot is None or self._exec_queue is None:
            return

        # Reset /new flag after first use
        sid = command.session_id
        if sid == "__new__":
            self._current_session_id = None

        # Start task tracking
        recent = self._tracker.get_recent_results(5)
        task = self._tracker.start_task(command.content, session_id=sid or "")

        # Save checkpoint before execution (for /undo)
        self._undo.save_checkpoint(task.id)

        # Build context prefix: dialogue history + project context
        context_parts: list = []

        # Inject dialogue history from message bus
        try:
            history = self._bus.get_history(limit=5)
            if history:
                context_parts.append(history)
        except Exception as e:
            logger.warning("Failed to get history from bus: %s", e)

        # Inject project context
        project_context = self._context.build(recent_results=recent)
        if project_context:
            context_parts.append(project_context)

        if context_parts:
            context_prefix = "\n\n".join(context_parts)
            enriched = Command(
                original_message=command.original_message,
                content=f"{context_prefix}\n\n用户指令: {command.content}",
                timestamp=command.timestamp,
                session_id=sid,
            )
            self._exec_queue.submit(enriched)
        else:
            self._exec_queue.submit(command)

        # Send start notification
        self._bot.send_text(self._formatter.format_start(command.content))

        # Store task ID for result tracking
        self._current_task_id = task.id

    def _submit_planned_task(self, goal: str) -> None:
        """Wrap a goal with planning instructions and submit to opencode.

        The prompt instructs opencode to plan steps first, then execute.
        """
        recent = self._tracker.get_recent_results(5)
        context = self._context.build(recent_results=recent)

        plan_prompt = (
            f"{context}\n\n"
            f"🎯 任务目标: {goal}\n\n"
            "请按以下流程操作：\n"
            "1. 先分析需求，列出完成目标所需步骤\n"
            "2. 逐步执行每个步骤\n"
            "3. 遇到错误先自行修复\n"
            "4. 完成后总结执行结果"
        )
        self._tracker.start_task(f"🎯 {goal}", steps=[
            "分析需求",
            "逐步执行",
            "验证结果",
        ])

        cmd = Command(
            original_message=WxMessage(
                id="plan", type=1, sender="system", roomid="",
                content=goal, timestamp=0,
            ),
            content=plan_prompt,
            timestamp=int(time.time()),
            session_id=self._supervisor_id or "__new__",
        )
        if self._exec_queue:
            self._exec_queue.submit(cmd)
        if self._bot:
            self._bot.send_text(f"🎯 规划任务: {goal}")

    # --- Intent-driven execution ---------------------------------------------

    def _execute_intent_command(self, intent, message: WxMessage) -> None:
        """Execute a built-in command matched from intent analysis."""
        cmd = intent.command
        args = intent.command_args or ""
        full_cmd = f"{cmd} {args}".strip()
        raw = f"/{full_cmd}"
        logger.info("Intent matched: %s", raw)
        self._handle_meta_command(raw)
        if self._bot:
            self._bot.send_text(f"🎯 识别到: {cmd}")

    def _execute_compound_intent(self, intent, message: WxMessage) -> None:
        """Execute compound task steps in sequence.

        LLM steps are submitted to queue; matched-command steps wait
        for artifacts (file paths) from previous LLM steps, then
        auto-inject them as command args.
        """
        if not self._bot:
            return

        steps = intent.steps
        total = len(steps)
        cmd_count = sum(1 for s in steps if s.matched_command)
        llm_count = total - cmd_count

        # Rough ETA: ~30s per LLM step, ~5s per built-in step
        eta_secs = llm_count * 30 + cmd_count * 5
        if eta_secs > 120:
            eta_str = f"{eta_secs // 60}-{(eta_secs // 60) + 1}分钟"
        else:
            eta_str = f"{eta_secs}秒"
        self._bot.send_text(
            f"📋 拆为{total}步"
            f"{f' ({cmd_count}步用内置指令)' if cmd_count > 0 else ''}"
            f"{f' ({llm_count}步用AI)' if llm_count > 0 else ''}"
            f"\n⏳ 预计: {eta_str}"
        )

        self._compound_ctx = {
            "steps": steps,
            "idx": 0,
            "total": total,
            "message": message,
            "artifacts": [],
            "sent_files": set(),
        }
        self._compound_next()

    def _compound_next(self) -> None:
        """Execute the next pending compound step."""
        ctx = getattr(self, "_compound_ctx", None)
        if not ctx:
            return

        steps = ctx["steps"]
        idx = ctx["idx"]
        total = ctx["total"]

        while idx < len(steps):
            step = steps[idx]
            i = idx + 1

            if step.matched_command:
                args = step.matched_args or ""
                # Auto-inject artifact path for /file commands
                if step.matched_command == "/file" and not args and ctx["artifacts"]:
                    # Use the first artifact that hasn't been sent yet
                    new_artifacts = [a for a in ctx["artifacts"] if a not in ctx.get("sent_files", set())]
                    if new_artifacts:
                        args = new_artifacts[0]
                        ctx.setdefault("sent_files", set()).add(new_artifacts[0])
                raw = f"/{step.matched_command} {args}".strip().rstrip("/")
                self._bot.send_text(f"  ⚡ {i}/{total}: {raw}")
                self._handle_meta_command(raw)
                idx += 1
                ctx["idx"] = idx
            else:
                self._bot.send_text(f"  🤖 {i}/{total}: {step.description}")
                prompt = (
                    f"{step.description}\n\n"
                    "完成后用 [FILE: 完整路径] 列出创建/修改的文件。"
                )
                cmd = Command(
                    original_message=ctx["message"],
                    content=prompt,
                    timestamp=ctx["message"].timestamp,
                    session_id=self._supervisor_id,
                )
                if self._exec_queue:
                    self._exec_queue.submit(cmd)
                ctx["idx"] = idx + 1
                return  # wait for _handle_result callback

        self._bot.send_text("✅ 全部完成")
        self._compound_ctx = None

    # --- Meta-command handling ------------------------------------------------

    def _handle_meta_command(self, content: str) -> bool:
        """Handle a meta-command (starting with ``/``).

        Returns ``True`` if the command was handled (caller should skip
        sending to opencode), ``False`` otherwise.
        """
        cmd = content[1:].strip().lower()  # strip leading /

        # Empty command — just "/" → show help
        if not cmd:
            return self._handle_meta_command("/help")

        # --- Abbreviation resolution ---
        base = cmd.split()[0]      # first word
        rest = cmd[len(base):]     # remaining args (leading space preserved)
        primary = _CMD_PRIMARY.get(base)
        if primary is None:
            # Not an exact match — try prefix matching
            matches = sorted({_CMD_PRIMARY[n] for n in _CMD_ALL if n.startswith(base)})
            if not matches:
                # Check digit-only (session switching: /1, /2, ...)
                if base.isdigit():
                    self._cmd_switch_session(int(base))
                    return True
                return False  # not a known command
            if len(matches) == 1:
                cmd = matches[0] + rest  # rebuild with full command name
            else:
                # Ambiguous → show candidates, wait for user selection
                self._cmd_selection = (matches, rest)
                if self._bot:
                    lines = [f'🔍 "/{base}" 匹配多个指令:']
                    for i, m in enumerate(matches, 1):
                        lines.append(f"  {i}. /{m} - {_CMD_DESC.get(m, '')}")
                    lines.append("回复编号选择，或 c 取消")
                    self._bot.send_text("\n".join(lines))  # type: ignore[union-attr]
                return True

        if cmd == "stop" or cmd == "restart":
            logger.info("Received restart command")
            if self._bot:
                self._bot.send_text("🔄 正在重启服务...")  # type: ignore[union-attr]
            self._restart_services()
            return True

        if cmd in ("new", "fresh"):
            # /new = cancel current worker + clear selected session
            if self._worker:
                self._worker.cancel()
            self._selected_worker_sid = None
            if self._bot:
                self._bot.send_text("✅ 已重置执行层，下一条任务使用新会话")  # type: ignore[union-attr]
            return True

        if cmd in ("help", "h", "?"):
            if self._bot:
                self._bot.send_text(  # type: ignore[union-attr]
                    "📋 全部指令\n\n"
                    "💬 任意文字 — 和监工对话\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "会话管理\n"
                    "  /new — 新建执行会话\n"
                    "  /sessions — 查看执行会话列表\n"
                    "  /1 /2 /3 — 切换到第 N 个会话\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "任务管理\n"
                    "  /plan 目标 — 规划并执行\n"
                    "  /tasks — 查看任务列表\n"
                    "  /task N — 查看任务详情\n"
                    "  /status — 查看当前状态\n"
                    "  /progress N — 设置进度报告间隔(秒)\n"
                    "  /cancel — 取消执行中的任务\n"
                    "  /undo — 撤销上次操作\n"
                    "  /cleartasks — 清空任务记录\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "上下文管理\n"
                    "  /compact — 压缩监工上下文\n"
                    "  /compact all — 压缩监工+执行层上下文\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "定时任务\n"
                    "  /cron — 管理定时任务（添加/查看/删除）\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "工具\n"
                    "  /screen — 截取电脑桌面\n"
                    "  /file 文件名 — 搜索并发送文件\n"
                    "  /focus 应用 — 切换窗口到前台\n"
                    "  /open 应用/文件 — 打开应用或文件\n"
                    "  /desktop — 显示桌面\n"
                    "  /min /max — 最小化/最大化\n"
                    "  /apps — 列出运行中的应用\n"
                    "  /cost — 查看费用统计\n"
                    "  /model — 查看/切换模型\n"
                    "  /ppt 主题 — 生成精美PPT\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "系统\n"
                    "  /restart — 重启服务\n"
                    "  /stop — 重启服务\n"
                    "  /help — 查看全部指令"
                )
            return True

        if cmd == "cost":
            if self._bot:
                self._bot.send_text(self._costs.format_summary())
            return True

        if cmd == "model" or cmd.startswith("model "):
            parts = cmd.split()
            if len(parts) >= 2:
                self._switch_model(parts[1])
            else:
                current = self._get_current_model()
                self._bot.send_text(f"当前模型: {current}\n/model flash 或 /model pro 切换")  # type: ignore[union-attr]
            return True

        if cmd in ("screen", "screenshot"):
            if not self._bot:
                return True
            self._bot.send_text("📸 正在截图...")  # type: ignore[union-attr]
            path = capture_desktop()
            if path:
                self._bot.send_image(path)  # type: ignore[union-attr]
            else:
                self._bot.send_text("❌ 截图失败（Playwright 未安装或出错）")  # type: ignore[union-attr]
            return True

        if cmd == "file" or cmd.startswith("file "):
            self._handle_file_command(cmd)
            return True

        # --- Window control commands (no LLM) ---

        if cmd == "desktop":
            ok, msg = show_desktop()
            if self._bot:
                self._bot.send_text(msg)  # type: ignore[union-attr]
            return True

        if cmd == "min":
            ok, msg = minimize_current()
            if self._bot:
                self._bot.send_text(msg)  # type: ignore[union-attr]
            return True

        if cmd == "max":
            ok, msg = maximize_current()
            if self._bot:
                self._bot.send_text(msg)  # type: ignore[union-attr]
            return True

        if cmd == "apps":
            if self._bot:
                self._bot.send_text(list_apps())  # type: ignore[union-attr]
            return True

        if cmd == "focus":
            if self._bot:
                self._bot.send_text("用法: /focus <应用名>\n例如: /focus chrome\n查看所有: /apps")  # type: ignore[union-attr]
            return True

        if cmd.startswith("focus "):
            query = cmd[6:].strip()
            ok, msg = focus_window(query)
            if ok:
                if self._bot:
                    self._bot.send_text(msg)  # type: ignore[union-attr]
            else:
                # Check if msg is a candidate list (contains numbered items)
                if msg.startswith("🔍"):
                    self._focus_query = query
                    if self._bot:
                        self._bot.send_text(msg)  # type: ignore[union-attr]
                else:
                    if self._bot:
                        self._bot.send_text(msg)  # type: ignore[union-attr]
            return True

        if cmd == "open":
            if self._bot:
                self._bot.send_text(  # type: ignore[union-attr]
                    "用法: /open <应用名或文件名>\n"
                    "例如: /open 微信\n"
                    "例如: /open 报告.docx"
                )
            return True

        if cmd.startswith("open "):
            query = cmd[5:].strip()
            ok, msg, candidates = open_app_or_file(query)
            if ok:
                if self._bot:
                    self._bot.send_text(msg)  # type: ignore[union-attr]
            elif candidates:
                # Ambiguous → store for selection
                self._open_query = query
                self._open_candidates = candidates
                if self._bot:
                    self._bot.send_text(msg)  # type: ignore[union-attr]
            else:
                if self._bot:
                    self._bot.send_text(msg)  # type: ignore[union-attr]
            return True

        if cmd.startswith("ppt "):
            topic = cmd[4:].strip()
            self._start_ppt_task(topic)
            return True
        if cmd == "ppt":
            self._bot.send_text("用法: /ppt 主题\n例如: /ppt AI发展趋势")  # type: ignore[union-attr]
            return True

        if cmd == "undo":
            result = self._undo.restore_last()
            if result:
                self._bot.send_text(f"⏪ 已撤销上一步操作\n{result}")  # type: ignore[union-attr]
            else:
                self._bot.send_text("⏪ 没有可撤销的操作")  # type: ignore[union-attr]
            return True

        if cmd in ("cancel", "stop worker"):
            if self._worker and self._worker.cancel():
                self._bot.send_text("❌ 已取消当前任务")  # type: ignore[union-attr]
            else:
                self._bot.send_text("没有正在执行的任务")  # type: ignore[union-attr]
            return True

        if cmd == "cleartasks":
            count = self._tracker.clear_all()
            if self._bot:
                self._bot.send_text(f"✅ 已清空 {count} 条任务记录")  # type: ignore[union-attr]
            return True

        if cmd == "compact":
            if not self._supervisor_id:
                if self._bot:
                    self._bot.send_text("❌ 监工会话未就绪")  # type: ignore[union-attr]
                return True
            if self._bot:
                self._bot.send_text("🔄 正在压缩对话上下文...")  # type: ignore[union-attr]
            try:
                result = self._session.execute(
                    "/compact", session_id=self._supervisor_id, timeout=60,
                )
                if self._bot:
                    self._bot.send_text(  # type: ignore[union-attr]
                        f"✅ 上下文已压缩\n{result.output[:200]}"
                    )
            except Exception as e:
                logger.error("Compact failed: %s", e)
                if self._bot:
                    self._bot.send_text(f"❌ 压缩失败: {e}")  # type: ignore[union-attr]
            return True

        if cmd.startswith("compact "):
            sub = cmd.split(None, 1)[1].strip()
            if sub in ("all", "both"):
                if self._bot:
                    self._bot.send_text("🔄 正在压缩所有会话上下文...")  # type: ignore[union-attr]
                summary = self._compact_both()
                if self._bot:
                    self._bot.send_text(f"✅ {summary}")  # type: ignore[union-attr]
                return True

        if cmd == "status":
            lines = []
            # Check supervisor message queue
            if self._exec_queue:
                if self._exec_queue.is_busy:
                    lines.append("⏳ 监工正在处理消息...")
                pending = self._exec_queue.pending_count
                if pending > 0:
                    lines.append(f"📋 队列中还有 {pending} 条待处理消息")
            # Check worker
            w = self._worker.worker if self._worker else None
            if w and w.status == "running":
                elapsed = time.time() - w.started_at
                lines.append(f"🤖 执行中: {w.task[:60]}")
                lines.append(f"   已运行: {int(elapsed)}s")
                if self._worker:
                    lines.append(f"   进度间隔: {self._worker.progress_interval}s")
            if not lines:
                self._bot.send_text("💤 空闲中，没有任务在执行")  # type: ignore[union-attr]
            else:
                self._bot.send_text("\n".join(lines))  # type: ignore[union-attr]
            return True

        if cmd.startswith("progress "):
            try:
                secs = int(cmd.split()[1])
            except (ValueError, IndexError):
                self._bot.send_text("格式: /progress N (N为秒数，最少10秒)")  # type: ignore[union-attr]
                return True
            if self._worker:
                self._worker.set_progress_interval(secs)
            if self._bot:
                self._bot.send_text(f"✅ 进度报告间隔已设为 {max(10, secs)} 秒")  # type: ignore[union-attr]
            return True
        if cmd == "progress":
            interval = self._worker.progress_interval if self._worker else 300
            self._bot.send_text(  # type: ignore[union-attr]
                f"当前进度报告间隔: {interval} 秒\n"
                f"修改: /progress N (最少10秒)"
            )
            return True

        if cmd.startswith("plan "):
            # /plan <goal> — wrap goal with planning instructions
            goal = content[6:].strip()  # strip "/plan "
            self._submit_planned_task(goal)
            return True

        if cmd in ("tasks", "task"):
            self._cmd_list_tasks()
            return True

        if cmd.startswith("task "):
            # /task <number> — show task detail
            try:
                num = int(cmd.split()[1])
                self._cmd_show_task(num)
            except (ValueError, IndexError):
                self._bot.send_text("格式: /task N (N为编号)")  # type: ignore[union-attr]
            return True

        if cmd in ("sessions", "list", "session"):
            self._cmd_list_sessions()
            return True

        # Check for session switch: /1, /2, /3 ...
        if cmd.isdigit():
            self._cmd_switch_session(int(cmd))
            return True

        return False  # not a meta-command, send to opencode

    def _cmd_list_sessions(self) -> None:
        """List recent worker (execution) sessions."""
        if not self._worker_history:
            self._bot.send_text("暂无执行会话记录")  # type: ignore[union-attr]
            return

        lines = ["📋 执行会话列表（最近10个）："]
        for i, h in enumerate(reversed(self._worker_history[-10:]), 1):
            status = "✅" if h.get("status") == "done" else "❌"
            task = h.get("task", "(无标题)")[:50]
            marker = " ← 当前" if h.get("session_id") == self._selected_worker_sid else ""
            lines.append(f"{i}. {status} {task}{marker}")
        lines.append("")
        lines.append("回复编号继续之前的会话，/new 重置")

        self._bot.send_text("\n".join(lines))  # type: ignore[union-attr]

    def _cmd_switch_session(self, num: int) -> None:
        """Switch to the *num*-th worker session in the history."""
        history_list = list(reversed(self._worker_history[-20:]))
        if num < 1 or num > len(history_list):
            self._bot.send_text(f"❌ 无效编号 {num}，请发送 /sessions 查看列表")  # type: ignore[union-attr]
            return

        target = history_list[num - 1]
        self._selected_worker_sid = target.get("session_id", "")
        task = target.get("task", "(无标题)")[:50]
        self._bot.send_text(f"✅ 已切换到执行会话 #{num}: {task}")  # type: ignore[union-attr]

    def _cmd_list_tasks(self) -> None:
        """List recent tasks with status."""
        tasks = self._tracker.list_recent(10)
        if not tasks:
            self._bot.send_text("暂无任务记录")  # type: ignore[union-attr]
            return

        lines = ["📋 任务列表（最近10个）："]
        status_icon = {"done": "✅", "failed": "❌", "running": "⏳"}
        for i, t in enumerate(tasks, 1):
            icon = status_icon.get(t.status, "⬜")
            lines.append(f"{i}. {icon} {t.goal[:60]}")
        lines.append("")
        lines.append("回复 /task N 查看详情")

        self._bot.send_text("\n".join(lines))  # type: ignore[union-attr]

    def _cmd_show_task(self, num: int) -> None:
        """Show detail for the *num*-th task."""
        tasks = self._tracker.list_recent(20)
        if num < 1 or num > len(tasks):
            self._bot.send_text(f"❌ 无效编号 {num}，请发送 /tasks 查看列表")  # type: ignore[union-attr]
            return

        task = tasks[num - 1]
        status_map = {"pending": "⬜", "running": "⏳", "done": "✅", "failed": "❌"}
        lines = [f"📌 任务 #{num}: {task.goal}", f"状态: {status_map.get(task.status, task.status)}"]
        if task.steps:
            lines.append("步骤:")
            for s in task.steps:
                icon = status_map.get(s.status, "⬜")
                desc = s.description[:50]
                lines.append(f"  {icon} {desc}")
                if s.output and s.output.strip():
                    out = s.output[:100]
                    lines.append(f"      {out}")

        self._bot.send_text("\n".join(lines))  # type: ignore[union-attr]

    def _handle_result(self, command: Command, result: ExecutionResult) -> None:
        """Callback from ExecutionQueue — format, intercept tags, send result."""
        if self._bot is None:
            return

        # Update task tracker
        if self._current_task_id:
            self._tracker.mark_complete(self._current_task_id, result.success)
            self._current_task_id = None

        # Track cost
        if result.session_id:
            self._costs.record(session_id=result.session_id)

        # Cost budget warning (after $0.50 per session)
        if result.session_id:
            session_cost = self._costs.get_session_cost(result.session_id)
            if session_cost > 0.5 and not hasattr(self, "_budget_warned"):
                self._budget_warned = True
                if self._bot:
                    self._bot.send_text(  # type: ignore[union-attr]
                        f"💰 费用提醒: 当前任务已花费 ${session_cost:.2f}，"
                        f"总计 ${self._costs.summary.total_cost:.4f}"
                    )

        output = result.output

        # --- Protocol tag interception ---

        # [TASK: ...] → extract and start worker
        if TAG_TASK in output and self._worker:
            match = re.search(r"\[TASK:\s*(.*?)\]", output, re.DOTALL)
            if match:
                task = match.group(1).strip().rstrip("]").strip()
                output = output[:match.start()] + output[match.end():]
                output = output.strip()

                # Use selected worker session if available
                sid = self._selected_worker_sid
                self._selected_worker_sid = None  # clear after use

                if self._worker.start_task(task):
                    # Track in history
                    self._worker_history.append({
                        "session_id": self._worker.worker.session_id,
                        "task": task,
                        "status": "running",
                    })
                    # Trim history
                    if len(self._worker_history) > 100:
                        self._worker_history = self._worker_history[-50:]
                    self._bot.send_text(f"🤖 已分配任务: {task[:80]}")
                else:
                    self._bot.send_text("⚠️ 任务启动失败（可能已有任务在执行）")

        # [CANCEL] from supervisor
        if TAG_CANCEL in output:
            if self._worker and self._worker.cancel():
                self._bot.send_text("❌ 任务已取消")
            else:
                self._bot.send_text("没有正在执行的任务")
            return

        # [FILE: ...] → intercept and send the file
        file_match = re.search(r"\[FILE:\s*([^\]]+)\]", output, re.IGNORECASE)
        if file_match:
            file_path = file_match.group(1).strip()
            output = output[:file_match.start()] + output[file_match.end():]
            output = output.strip()
            if self._bot:
                self._send_file_and_notify(file_path)
            if not output:
                return  # nothing else to display

        # [确认: ...] reply from user → route to worker
        if TAG_CONFIRM in output and self._worker and self._worker.is_running:
            self._session.execute_async(
                f"用户回复: {output}",
                session_id=self._worker.worker.session_id,
            )
            self._bot.send_text("✅ 已转发给执行层")
            return

        # --- Send the cleaned result (single pass) ---
        # Filter out meaningless timeout/no-output responses
        if not result.success and (not output or output in ("(no output)", "Error: unknown", "")):
            output = f"⏰ 任务执行超时 ({result.duration_seconds:.0f}s)，请重试或拆分任务"

        parts = self._formatter.format_result(
            ExecutionResult(success=result.success, output=output, duration_seconds=result.duration_seconds)
        )

        for part in parts:
            self._bot.send_text(part.content)

        # Show git diff
        if result.success and self._git.has_changes():
            diff_stat = self._git.get_stat()
            if diff_stat:
                self._bot.send_text(f"📝 文件变更:\n{diff_stat}")
            diff = self._git.get_diff(max_lines=40, max_size=2000)
            if diff:
                self._bot.send_text(f"```diff\n{diff}\n```")

        # Proactive notification
        if result.duration_seconds > 10:
            status = "✅ 完成" if result.success else "❌ 失败"
            self._bot.send_text(
                f"{status} (耗时 {result.duration_seconds:.0f}s)"
                f"{' 💰 /cost 查看费用' if result.success else ''}"
            )

        # --- Scan LLM output for file artifacts + continue compound chain ---
        if result.success and output:
            artifacts = extract_artifacts(output)
            if artifacts:
                for path in artifacts[:3]:
                    self._send_file_and_notify(path)
                # Store for compound context
                ctx = getattr(self, "_compound_ctx", None)
                if ctx:
                    ctx["artifacts"].extend(artifacts)
        # Continue compound task if pending
        ctx = getattr(self, "_compound_ctx", None)
        if ctx and ctx["idx"] > 0:
            self._compound_next()

    # ── Context compaction (idle-based) -------------------------------------

    def _start_compact_monitor(self) -> None:
        """Background thread: compact only after 1h user idle + 300+ messages."""
        def _loop() -> None:
            while self._shutdown and not self._shutdown.shutdown_event.is_set():
                time.sleep(60)  # lightweight wake-up
                now = time.time()
                idle = now - self._last_active_time
                if idle < self._COMPACT_IDLE_SECONDS:
                    continue  # user still talking
                in_cooldown = (now - self._last_compact_time) < self._COMPACT_COOLDOWN
                if in_cooldown:
                    continue
                self._check_idle_compact()

        t = threading.Thread(target=_loop, daemon=True)
        t.start()
        logger.info("Compact monitor started (idle=%ds, limit=%d, cooldown=%ds)",
                     self._COMPACT_IDLE_SECONDS, self._COMPACT_MESSAGE_LIMIT,
                     self._COMPACT_COOLDOWN)

    def _check_idle_compact(self) -> None:
        """Check both sessions and compact if message count exceeds limit."""
        if not self._bot:
            return
        for name, sid, sess in [("监工", self._supervisor_id, self._session),
                                 ("执行层", self._worker.worker.session_id, self._worker_session)
                                 ] if self._supervisor_id else []:
            if not sid:
                continue
            try:
                count = sess.get_message_count(sid)
                if count >= self._COMPACT_MESSAGE_LIMIT:
                    logger.info("Idle compact %s: %d messages", name, count)
                    r = sess.execute("/compact", session_id=sid, timeout=60)
                    if r.success:
                        self._last_compact_time = time.time()
                        self._bot.send_text(
                            f"🔄 检测到已{self._COMPACT_IDLE_SECONDS // 60}分钟未操作，"
                            f"已自动压缩{name}上下文 ({count}条消息)")
            except Exception as e:
                logger.debug("Idle compact %s error: %s", name, e)

    def _compact_both(self) -> str:
        """Compact both supervisor and Worker sessions. Returns a summary string."""
        results = []

        if self._supervisor_id:
            try:
                r = self._session.execute("/compact", session_id=self._supervisor_id, timeout=60)
                if r.success:
                    results.append("监工 ✅")
                else:
                    results.append(f"监工 ❌ ({r.output[:60]})")
            except Exception as e:
                results.append(f"监工 ❌ ({e})")

        if self._worker and self._worker.worker.session_id:
            try:
                r = self._worker_session.execute("/compact", session_id=self._worker.worker.session_id, timeout=60)
                if r.success:
                    results.append("执行层 ✅")
                else:
                    results.append(f"执行层 ❌ ({r.output[:60]})")
            except Exception as e:
                results.append(f"执行层 ❌ ({e})")

        return "上下文已压缩: " + ", ".join(results) if results else "没有可压缩的会话"

    def _handle_file_command(self, raw_cmd: str) -> None:
        """Handle /file command.

        Two modes:
          1. Absolute path (e.g. C:/Users/.../file.docx) → try direct send
          2. Anything else → submit to supervisor for interactive file search
        """
        # Extract query — strip "file " prefix (cmd already has no leading /)
        if raw_cmd.startswith("file "):
            query = raw_cmd[5:].strip()
        else:
            query = raw_cmd[4:].strip()

        if not query:
            if self._bot:
                self._bot.send_text(  # type: ignore[union-attr]
                    "用法: /file <路径或描述>\n"
                    "明确路径: /file C:/Users/1/Desktop/报告.docx\n"
                    "模糊描述: /file 配置文件"
                )
            return

        logger.info("File command: query=%s", query)

        # --- Mode 1: Absolute path ---
        if os.path.isabs(query):
            norm = os.path.normpath(query)
            if os.path.isfile(norm):
                self._send_file_and_notify(norm)
                return
            # Path doesn't exist → submit to supervisor to help locate it
            prompt = self._build_file_interaction_prompt(
                query, extra=(
                    f"用户提供了一个绝对路径但文件不存在: {norm}\n"
                    "请告诉用户该路径不存在，然后按流程帮助用户找到文件。"
                ),
            )
        else:
            # --- Mode 2: Natural language → supervisor handles interaction ---
            prompt = self._build_file_interaction_prompt(query)

        # Submit to supervisor (skip _submit_command to avoid "🚀 执行" notification)
        cmd = Command(
            original_message=WxMessage(
                id="file", type=1, sender="system", roomid="",
                content=query, timestamp=int(time.time()),
            ),
            content=prompt,
            timestamp=int(time.time()),
            session_id=self._supervisor_id,
        )
        if self._exec_queue:
            self._exec_queue.submit(cmd)
        if self._bot:
            self._bot.send_text(f"🔍 正在帮你找文件: {query}")  # type: ignore[union-attr]

    def _build_file_interaction_prompt(self, query: str, extra: str = "") -> str:
        """Build a prompt instructing the supervisor to interactively help find a file."""
        return f"""用户想获取文件: "{query}"
{extra}
请按以下流程帮助用户找到并发送文件，每次只做一个步骤:

**第1步 - 确认位置:**
先询问用户文件大概在哪个目录，列出常见位置供选择:
  1. 桌面 (C:\\Users\\1\\Desktop)
  2. 下载 (C:\\Users\\1\\Downloads)
  3. 文档 (C:\\Users\\1\\Documents)
  4. D盘根目录 (D:\\)
  5. E盘根目录 (E:\\)
  6. 微信接收文件 (C:\\Users\\1\\Documents\\WeChat Files)
  7. 其他（请用户输入完整路径）

**第2步 - 列出文件:**
用户选择位置后，用 list 工具列出该目录下的所有文件（跳过子目录），
按修改时间倒序排列，最多显示 30 个文件，带编号。
格式: 1. 文件名 (大小) - 修改时间

**第3步 - 确认发送:**
用户通过编号或文件名选择后，确认文件存在，回复:
[FILE: <完整绝对路径>]

用户也可以说"搜索子目录"让系统递归搜索，
或者说具体关键词缩小范围。

重要: 每次只展示一个步骤的结果，等用户回复后再进行下一步。"""

    def _send_file_and_notify(self, path: str) -> None:
        """Send file to user with a notification message."""
        if self._bot is None:
            return

        if not os.path.isfile(path):
            self._bot.send_text(f"❌ 文件不存在: {path}")  # type: ignore[union-attr]
            return

        name = os.path.basename(path)
        try:
            size_kb = os.path.getsize(path) / 1024
        except OSError:
            size_kb = 0
        size_str = f"{size_kb:.1f}KB" if size_kb < 1024 else f"{size_kb / 1024:.1f}MB"

        self._bot.send_text(f"📎 发送文件: {name} ({size_str})")  # type: ignore[union-attr]
        try:
            self._bot.send_file(path)  # type: ignore[union-attr]
        except Exception as e:
            logger.error("Failed to send file %s: %s", path, e)
            self._bot.send_text(f"❌ 发送失败: {e}")  # type: ignore[union-attr]

    def _handle_cmd_selection(self, reply: str) -> bool:
        """Handle user picking from ambiguous command abbreviations.

        Returns True if handled (caller should skip further processing).
        """
        sel = self._cmd_selection
        if sel is None:
            return False
        matches, rest = sel

        reply = reply.strip().lower()
        if reply in ("c", "cancel", "取消", "q"):
            self._cmd_selection = None
            if self._bot:
                self._bot.send_text("❌ 已取消")  # type: ignore[union-attr]
            return True

        try:
            idx = int(reply) - 1
        except ValueError:
            if self._bot:
                self._bot.send_text("请输入数字编号，或回复 c 取消")  # type: ignore[union-attr]
            return True

        if idx < 0 or idx >= len(matches):
            if self._bot:
                self._bot.send_text(  # type: ignore[union-attr]
                    f"编号超出范围 (1-{len(matches)})，请重新选择"
                )
            return True

        chosen = matches[idx]
        self._cmd_selection = None

        # Rebuild the full command and re-enter meta-command handler
        full_content = "/" + chosen + rest
        return self._handle_meta_command(full_content)

    def _handle_focus_selection(self, reply: str) -> bool:
        """Handle user picking from focus candidate list."""
        query = self._focus_query
        if query is None:
            return False

        reply = reply.strip().lower()
        if reply in ("c", "cancel", "取消", "q"):
            self._focus_query = None
            if self._bot:
                self._bot.send_text("❌ 已取消")  # type: ignore[union-attr]
            return True

        try:
            idx = int(reply) - 1
        except ValueError:
            if self._bot:
                self._bot.send_text("请输入数字编号选择，或回复 c 取消")  # type: ignore[union-attr]
            return True

        ok, msg = focus_window_by_index(query, idx)
        self._focus_query = None
        if self._bot:
            self._bot.send_text(msg)  # type: ignore[union-attr]
        return True

    def _handle_open_selection(self, reply: str) -> bool:
        """Handle user picking from open candidate list (files or locations)."""
        query = self._open_query
        candidates = self._open_candidates
        if query is None or candidates is None:
            return False

        reply = reply.strip().lower()
        if reply in ("c", "cancel", "取消", "q"):
            self._open_query = None
            self._open_candidates = None
            if self._bot:
                self._bot.send_text("❌ 已取消")  # type: ignore[union-attr]
            return True

        # Handle "y" for subdirectory confirmation
        if reply == "y" and candidates and candidates[0].get("type") == "confirm_subdirs":
            ok, msg, new_candidates = open_by_index(query, 0, candidates)
            if new_candidates:
                # Round 2 returned more candidates
                self._open_candidates = new_candidates
                if self._bot:
                    self._bot.send_text(msg)  # type: ignore[union-attr]
            else:
                self._open_query = None
                self._open_candidates = None
                if self._bot:
                    self._bot.send_text(msg)  # type: ignore[union-attr]
            return True

        try:
            idx = int(reply) - 1
        except ValueError:
            if self._bot:
                self._bot.send_text("请输入数字编号，或回复 c 取消")  # type: ignore[union-attr]
            return True

        ok, msg, new_candidates = open_by_index(query, idx, candidates)

        if new_candidates:
            # Selection resulted in another candidate list (e.g. location → file list)
            self._open_candidates = new_candidates
            if self._bot:
                self._bot.send_text(msg)  # type: ignore[union-attr]
        else:
            # Final result
            self._open_query = None
            self._open_candidates = None
            if self._bot:
                self._bot.send_text(msg)  # type: ignore[union-attr]
        return True

    def _handle_queued(self, command: Command, position: int) -> None:
        """Callback from ExecutionQueue — notify user of queue position."""
        if self._bot is None:
            return
        msg = self._formatter.format_queued(position)
        self._bot.send_text(msg)

    def _setup_logging(self) -> None:
        """Configure logging based on config."""
        log_level = getattr(logging, self._config.service.log_level.upper(), logging.INFO)
        logging.basicConfig(
            level=log_level,
            format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler(self._config.service.log_file, encoding="utf-8"),
            ],
        )
