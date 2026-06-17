"""Simple cron scheduler — natural language timed tasks using schedule library.

Usage:
    User says: "每天早上九点发AI资讯" 
    → /cron add 每天 09:00 发送AI资讯摘要
"""

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import schedule

from wechat_opencode.types import BotABC

logger = logging.getLogger(__name__)


@dataclass
class CronJob:
    """A scheduled task."""
    id: str
    schedule_text: str  # human-readable: "每天 09:00"
    prompt: str          # what to execute
    job_func: Optional[Callable] = None  # schedule Job reference
    enabled: bool = True
    last_run: float = 0.0
    run_count: int = 0


class CronScheduler:
    """Manages scheduled tasks that run automatically."""

    def __init__(self, bot: BotABC, on_execute: Callable[[str], None]) -> None:
        self._bot = bot
        self._on_execute = on_execute
        self._jobs: dict[str, CronJob] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._next_id = 1

    def start(self) -> None:
        """Start the scheduler background thread."""
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("CronScheduler started")

    def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        schedule.clear()
        logger.info("CronScheduler stopped")

    def add_job(self, schedule_expr: str, prompt: str) -> Optional[str]:
        """Add a scheduled task.

        Args:
            schedule_expr: e.g. "每天 09:00", "每30分钟", "周一到周五 08:00"
            prompt: The task to execute

        Returns:
            Job ID string if added, None on failure.
        """
        job_id = f"cron_{self._next_id}"
        self._next_id += 1

        job = CronJob(id=job_id, schedule_text=schedule_expr, prompt=prompt)

        # Schedule using human-readable expressions
        parsed = self._parse_schedule(schedule_expr)
        if parsed is None:
            return None

        interval, unit, at_time = parsed

        if at_time:
            job.job_func = getattr(
                schedule.every(interval).__getattribute__(unit),
                "at",
            )(at_time).do(self._run_job, job_id)
        else:
            job.job_func = getattr(
                schedule.every(interval),
                unit,
            ).do(self._run_job, job_id)

        self._jobs[job_id] = job
        logger.info("Cron job added: %s — %s at %s", job_id, prompt, schedule_expr)
        return job_id

    def remove_job(self, job_id: str) -> bool:
        """Remove a scheduled job by ID."""
        if job_id not in self._jobs:
            return False
        schedule.cancel_job(self._jobs[job_id].job_func)
        del self._jobs[job_id]
        logger.info("Cron job removed: %s", job_id)
        return True

    def list_jobs(self) -> list[CronJob]:
        """Return all registered jobs."""
        return list(self._jobs.values())

    def _parse_schedule(self, expr: str):
        """Parse human-readable schedule expression.

        Returns (interval, unit, at_time) or None.
        """
        expr = expr.strip().lower()

        # "每N分钟" / "每N小时"
        m = re.match(r'^每(\d+)(分钟|小时|天|周)$', expr)
        if m:
            return (int(m.group(1)), _UNIT_MAP[m.group(2)], None)

        # "每天 HH:MM" / "每日 HH:MM"
        m = re.match(r'^(每天|每日)\s+(\d{1,2}:\d{2})$', expr)
        if m:
            return (1, "days", m.group(2))

        # "周一到周五 HH:MM" / "工作日 HH:MM"
        m = re.match(r'^(周一到周五|工作日|周一至周五)\s+(\d{1,2}:\d{2})$', expr)
        if m:
            return (1, "monday", m.group(2))  # schedule starts on monday

        # "每周X HH:MM"
        days = {"周一": "monday", "周二": "tuesday", "周三": "wednesday",
                "周四": "thursday", "周五": "friday", "周六": "saturday", "周日": "sunday"}
        for cn, en in days.items():
            if expr.startswith(cn):
                m = re.match(rf'^{cn}\s+(\d{{1,2}}:\d{{2}})$', expr)
                if m:
                    return (1, en, m.group(1))

        # "每隔N小时" / "每隔N分钟"
        m = re.match(r'^每隔(\d+)(小时|分钟)$', expr)
        if m:
            return (int(m.group(1)), _UNIT_MAP[m.group(2)], None)

        return None

    def _run_job(self, job_id: str) -> None:
        """Execute a scheduled job."""
        job = self._jobs.get(job_id)
        if not job or not job.enabled:
            return
        try:
            logger.info("Cron job firing: %s — %s", job_id, job.prompt)
            job.last_run = time.time()
            job.run_count += 1
            # Execute via the callback (submits to the execution queue)
            self._on_execute(job.prompt)
        except Exception as e:
            logger.error("Cron job %s failed: %s", job_id, e)

    def _loop(self) -> None:
        """Background thread: run pending scheduled tasks."""
        while self._running:
            try:
                schedule.run_pending()
            except Exception as e:
                logger.error("Cron scheduler error: %s", e)
            time.sleep(10)


_UNIT_MAP = {
    "分钟": "minutes",
    "小时": "hours",
    "天": "days",
    "周": "weeks",
}
