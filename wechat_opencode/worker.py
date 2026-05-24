"""Worker manager — manage the execution session, poll progress, route results."""

import logging
import re
import threading
import time
from typing import Callable, List, Optional

from wechat_opencode.session import OpenCodeSession
from wechat_opencode.types import (
    TAG_CANCEL, TAG_CONFIRM, TAG_PROGRESS, TAG_RESULT, TAG_TASK,
    WorkerState,
)

logger = logging.getLogger(__name__)


class WorkerManager:
    """Manages a single execution (worker) session.

    The supervisor is the main session the user chats with.
    The worker does the actual work in a separate session.
    This manager bridges the two.
    """

    def __init__(
        self,
        session: OpenCodeSession,
        supervisor_id: str,
        on_inject: Callable[[str], None],
        on_notify: Callable[[str], None],
        on_confirm: Callable[["WorkerManager"], None],
        on_finish: Callable[[str, bool], None],  # (session_id, success)
        on_rollback: Optional[Callable[[], Optional[str]]] = None,
        poll_interval: int = 5,
        max_run_seconds: int = 1800,
    ) -> None:
        self._session = session
        self._supervisor_id = supervisor_id
        self._on_inject = on_inject
        self._on_notify = on_notify
        self._on_confirm = on_confirm
        self._on_finish = on_finish
        self._on_rollback = on_rollback
        self._poll_interval = poll_interval
        self._max_run_seconds = max_run_seconds

        self._worker: WorkerState = WorkerState()
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._last_message_id = ""
        self._cancel_requested = False
        self._progress_interval = 300  # seconds, configurable via /progress

    # --- Public API -----------------------------------------------------------

    def start_task(self, task: str) -> bool:
        """Start a new task on a fresh worker session."""
        if self._worker.status == "running":
            return False  # already working

        sid = self._session.create_session(title=f"Worker: {task[:50]}")
        if not sid:
            return False

        self._worker = WorkerState(
            session_id=sid, task=task, status="running",
            started_at=time.monotonic(), updated_at=time.monotonic(),
        )

        # Send system prompt + task to worker
        win_cheatsheet = (
            "Windows 操控速查 (PowerShell):\n"
            "  音量: (New-Object -ComObject WScript.Shell).SendKeys(键)\n"
            "  亮度: (Get-WmiObject -Namespace root/wmi -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1,亮度%)\n"
            "  显示: Get-WmiObject Win32_VideoController | fl; 分辨率切换改注册表\n"
            "  蓝牙: Get-PnpDevice -Class Bluetooth | where Status -eq OK\n"
            "  通知: 安装 BurntToast 后 New-BurntToastNotification -Text 标题,内容\n"
            "  打印: Get-Printer; Start-Process -FilePath 文件 -Verb Print -PassThru\n"
            "  安装: winget install 名称 --silent\n"
            "  输入法: Get-WinUserLanguageList; Set-WinUserLanguageList -LanguageList zh-CN\n"
            "  注册表: reg query/add/delete; Set-ItemProperty\n"
            "  电源: shutdown /s /t 0(关机); shutdown /r /t 0(重启); rundll32.exe user32.dll,LockWorkStation(锁屏); powercfg /setactive 计划(切换电源计划)\n"
            "  任务: schtasks /create /tn 名 /tr 命令 /sc daily /st 时间\n"
            "  壁纸: Set-ItemProperty 'HKCU:\\Control Panel\\Desktop' -Name WallPaper -Value 路径; rundll32.exe user32.dll,UpdatePerUserSystemParameters,1,True\n"
            "  网络: arp -a(扫描局域网); Wake-On-Lan: powercfg /deviceenablewake 设备名\n"
            "  文件: Remove-Item(删); Copy-Item(复制); Move-Item(移动); Rename-Item(重命名)\n"
            "  进程: Get-Process(查); Stop-Process -Name 名 -Force(杀); Start-Process(启动)\n"
            "  系统: Get-ComputerInfo; systeminfo | more; Get-Service\n"
        )
        sys_prompt = (
            "你是执行层，自动完成任务。无法和用户直接交互。\n\n"
            "═══ 核心原则 ═══\n"
            "• 目标导向 — 不达目标不停止\n"
            "• 自动修复 — 出错先自查原因，再换方案\n"
            "• 成本意识 — 重试不超过3次，超过汇报原因\n"
            "• 安全第一 — 删除/覆盖前先备份\n\n"
            "═══ 执行循环 ═══\n"
            "收到任务后按以下流程，每步做完立即汇报:\n\n"
            "1. 分析需求 → 列出完成目标所需的步骤清单\n"
            "2. 逐步执行 → 每步完成后 → 验证结果\n"
            "3. 成功? → 继续下一步\n"
            "   失败? → 分析原因 → 换方案重试\n"
            "     第1次: 立即重试 (可能是网络/临时故障)\n"
            "     第2次: 换参数/路径/端口/镜像源\n"
            "     第3次: 换工具 (pip→conda, curl→wget, 端口→其他端口)\n"
            "     3次仍失败 → [结果: 失败 已尝试:A/B/C,原因是X,建议Y]\n"
            "4. 缺少工具/包 → 自己安装 → 继续\n"
            "5. 全部步骤完成 → 最终验证 → [结果: 成功 做了什么]\n\n"
            "═══ 验证清单 ═══\n"
            "每步执行后必须验证，用工具实际操作:\n"
            "  写代码 → 运行并检查输出 / 跑测试 / 检查语法\n"
            "  创建文件 → 检查文件存在且大小>0\n"
            "  安装软件 → 运行 --version 确认可执行\n"
            "  修改配置 → 解析配置 / 检查关键字段\n"
            "  网络请求 → 检查状态码 / 重试3次\n"
            "  启动服务 → 检查端口是否监听\n"
            "  Git操作 → git status 确认状态\n\n"
            "═══ 安全规则 ═══\n"
            "• 删除文件前先备份 (copy → 确认副本存在 → 再删除)\n"
            "• 覆盖文件前先备份 (copy 原文件 → .bak → 再写入)\n"
            "• 修改系统配置前先导出原配置\n"
            "• 不确定的操作 → [确认: 问题 选项:A/B]\n\n"
            "═══ 协议格式 ═══\n"
            "  [进度: 步骤2/5 正在安装 pandas (第1次尝试)]\n"
            "  [进度: 步骤3/5 已创建 app.py → 验证: 语法正确]\n"
            "  [确认: 端口8080被占，选哪个？ 选项: A:8081 B:3000]\n"
            "  [结果: 成功 已创建Flask项目，5/5步骤全部完成]\n"
            "  [结果: 失败 安装mysql失败: 已尝试pip/conda/手动下载, 需管理员权限]\n\n"
            f"{win_cheatsheet}\n"
            f"用户要你做: {task}\n"
            "拆解步骤，逐步执行并验证。现在开始。"
        )
        if not self._session.execute_async(sys_prompt, session_id=sid):
            self._worker.status = "idle"
            return False

        self._running = True
        self._cancel_requested = False
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        logger.info("Worker started: %s → %s", sid, task[:60])
        return True

    def cancel(self) -> bool:
        """Request cancellation of the current task."""
        if self._worker.status != "running":
            return False
        self._cancel_requested = True
        # Abort the worker session
        try:
            self._session._api_post(
                f"/session/{self._worker.session_id}/abort", {}, timeout=5,
            )
        except Exception:
            pass
        self._worker.status = "idle"
        return True

    @property
    def worker(self) -> WorkerState:
        return self._worker

    @property
    def is_running(self) -> bool:
        return self._worker.status == "running"

    @property
    def progress_interval(self) -> int:
        """Current progress reporting interval in seconds."""
        return self._progress_interval

    def set_progress_interval(self, seconds: int) -> None:
        """Change progress reporting interval (minimum 10 seconds)."""
        self._progress_interval = max(10, seconds)

    def start_with_prompt(self, task: str, prompt: str) -> bool:
        """Start a task with a custom system prompt (e.g., PPT designer role)."""
        sid = self._session.create_session(title=f"Task: {task[:40]}")
        if not sid:
            return False

        self._worker = WorkerState(
            session_id=sid, task=task, status="running",
            started_at=time.monotonic(), updated_at=time.monotonic(),
        )

        full_prompt = prompt + f"\n\n用户需求: {task}"
        if not self._session.execute_async(full_prompt, session_id=sid):
            self._worker.status = "idle"
            return False

        self._running = True
        self._cancel_requested = False
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        logger.info("Worker started with custom prompt: %s", sid)
        return True

    # --- Internal -------------------------------------------------------------

    def _poll_loop(self) -> None:
        """Background thread: poll worker for new messages, route tags."""
        deadline = time.monotonic() + self._max_run_seconds
        last_progress_time = time.monotonic()
        last_progress_report = time.monotonic()  # periodic user-visible progress

        while self._running and time.monotonic() < deadline:
            if self._cancel_requested:
                self._finish(cancelled=True)
                return

            time.sleep(self._poll_interval)
            elapsed = time.monotonic() - self._worker.started_at

            # Periodic progress report to user (configurable interval)
            if time.monotonic() - last_progress_report >= self._progress_interval:
                last_progress_report = time.monotonic()
                mins = int(elapsed / 60)
                secs = int(elapsed % 60)
                progress_msg = (
                    f"[进度: 执行中 {mins}分{secs}秒] "
                    f"任务: {self._worker.task[:40]}"
                )
                self._on_notify(f"⏳ {progress_msg}")
                self._on_inject(progress_msg)

            # Poll for new messages
            new_msgs = self._session.poll_messages(
                self._worker.session_id, self._last_message_id,
            )
            if not new_msgs:
                # Check for timeout (no response in 10 minutes)
                if time.monotonic() - last_progress_time > 600:
                    self._on_notify("⚠️ 执行层无响应超过10分钟，可能卡住了")
                    self._finish(timeout=True)
                    return
                continue

            last_progress_time = time.monotonic()
            self._process_responses(new_msgs)

        # Check if we timed out
        if time.monotonic() >= deadline:
            self._finish(timeout=True)

    def _process_responses(self, messages: List[dict]) -> None:
        """Process new messages from the worker, routing tags appropriately."""
        for msg in messages:
            text = msg.get("text", "")

            if self._cancel_requested:
                return

            if TAG_CANCEL in text:
                self._finish(cancelled=True)
                return

            if TAG_RESULT in text:
                self._worker.last_text = text
                # Extract result and inject into supervisor
                self._on_inject(f"[结果: {text}]")
                self._finish(success="成功" in text)
                return

            if TAG_CONFIRM in text:
                # Forward confirmation to user and set confirm pending
                self._on_notify(f"⚠️ 执行层需要确认:\n{text}")
                self._on_confirm(self)
                continue

            if TAG_PROGRESS in text:
                # Inject into supervisor AND notify user directly
                self._on_inject(f"[进度: {text}]")
                self._on_notify(f"📊 {text}")
                self._worker.last_text = text
                continue

    def _finish(self, success: bool = False, cancelled: bool = False, timeout: bool = False) -> None:
        """Mark the worker as finished."""
        self._running = False
        self._worker.status = "idle"
        self._worker.updated_at = time.monotonic()

        # Auto-rollback on failure (restore git stash)
        if not success and not cancelled and self._on_rollback:
            try:
                result = self._on_rollback()
                if result:
                    self._on_notify(f"↩️ 已自动回滚: {result}")
            except Exception:
                pass

        self._on_finish(self._worker.session_id, success)

        if cancelled:
            self._on_notify("❌ 任务已取消")
        elif timeout:
            self._on_notify("⏰ 任务执行超时，已自动终止")
        elif success:
            self._on_notify("✅ 任务执行完成")
        else:
            self._on_notify("⚠️ 任务执行结束")
