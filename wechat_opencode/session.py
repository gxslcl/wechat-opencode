"""OpenCode session manager — manage opencode serve and communicate via HTTP API."""

import logging
import shutil
import socket
import subprocess
import time
from typing import Any, Dict, List, Optional

import requests

from wechat_opencode.config import Config
from wechat_opencode.types import ExecutionResult

logger = logging.getLogger(__name__)

_OPCODE_PATH: Optional[str] = None


def _resolve_opencode() -> str:
    """Find the full path to the opencode CLI executable."""
    global _OPCODE_PATH
    if _OPCODE_PATH is not None:
        return _OPCODE_PATH

    path = shutil.which("opencode") or shutil.which("opencode.cmd")
    if path:
        _OPCODE_PATH = path
        return path

    raise RuntimeError(
        "opencode CLI not found in PATH. "
        "Install it from https://github.com/opencode-ai/opencode"
    )


class OpenCodeSession:
    """Manages a persistent opencode serve process, communicates via HTTP API."""

    def __init__(self, config: Config, serve_port: Optional[int] = None) -> None:
        self._config = config
        self._serve_port = serve_port or config.opencode.serve_port
        self._serve_process: Optional[subprocess.Popen] = None
        self._server_url: str = ""

    # --- Serve lifecycle ------------------------------------------------------

    def start_serve(self, extra_args: Optional[List[str]] = None) -> str:
        """Start opencode serve as a subprocess. Returns the server URL.

        *extra_args* are added to the CLI command (e.g. ``["--pure"]``).
        """
        if self.is_serve_running():
            return self._server_url

        port = self._serve_port
        host = self._config.opencode.serve_host

        # Kill any leftover process on this port
        self._kill_port_occupant(port)

        opencode_path = _resolve_opencode()
        cmd = [opencode_path, "serve", "--port", str(port), "--hostname", host]
        if extra_args:
            cmd.extend(extra_args)

        logger.info("Starting opencode web: %s", " ".join(cmd))
        self._serve_process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

        for _ in range(20):
            if not self.is_serve_running():
                raise RuntimeError("opencode serve process exited unexpectedly")
            try:
                with socket.create_connection((host, port), timeout=1):
                    break
            except (ConnectionRefusedError, OSError):
                time.sleep(0.5)
        else:
            self.stop_serve()
            raise RuntimeError(f"opencode serve did not become ready on {host}:{port}")

        self._server_url = f"http://{host}:{port}"
        logger.info("opencode serve ready at %s", self._server_url)

        # Wait for the HTTP API to be ready (port is open, but routes need init)
        if not self._wait_for_api_ready(timeout=15):
            self.stop_serve()
            raise RuntimeError("opencode serve HTTP API did not become ready")

        return self._server_url

    @staticmethod
    def _kill_port_occupant(port: int) -> None:
        """Kill any process listening on the given port (Windows only)."""
        import subprocess as sp
        try:
            result = sp.run(
                ["netstat", "-ano"], capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.splitlines():
                if f":{port}" in line and "LISTENING" in line:
                    pid = line.strip().split()[-1]
                    try:
                        sp.run(["taskkill", "/F", "/PID", pid],
                               capture_output=True, timeout=5)
                        logger.info("Killed old process on port %d (PID %s)", port, pid)
                    except Exception:
                        pass
                    break
        except Exception:
            pass

    def stop_serve(self) -> None:
        """Stop the opencode serve subprocess."""
        if self._serve_process is not None:
            logger.info("Stopping opencode serve...")
            self._serve_process.terminate()
            try:
                self._serve_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._serve_process.kill()
                self._serve_process.wait(timeout=2)
            self._serve_process = None
            self._server_url = ""
            logger.info("opencode serve stopped")

    def is_serve_running(self) -> bool:
        """Check if opencode serve process is alive."""
        return self._serve_process is not None and self._serve_process.poll() is None

    # --- HTTP helpers ---------------------------------------------------------

    def _api_get(self, path: str, timeout: int = 10) -> Any:
        """GET request to the opencode server API."""
        if not self.is_serve_running():
            raise RuntimeError("opencode serve is not running")
        return requests.get(
            f"{self._server_url}{path}",
            headers={"Accept": "application/json"},
            timeout=timeout,
        ).json()

    def _api_post(self, path: str, body: dict, timeout: int = 300) -> Any:
        """POST request to the opencode server API."""
        if not self.is_serve_running():
            raise RuntimeError("opencode serve is not running")
        return requests.post(
            f"{self._server_url}{path}",
            json=body,
            headers={"Accept": "application/json"},
            timeout=timeout,
        ).json()

    def _wait_for_api_ready(self, timeout: int = 15) -> bool:
        """Wait for the HTTP API `/session` endpoint to become responsive."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self.is_serve_running():
                return False
            try:
                r = requests.get(
                    f"{self._server_url}/session",
                    headers={"Accept": "application/json"},
                    timeout=3,
                )
                if r.status_code == 200:
                    logger.info("opencode HTTP API is ready")
                    return True
            except Exception:
                pass
            time.sleep(1)
        return False

    # --- Session management (HTTP API) ---------------------------------------

    def create_session(self, title: str = "") -> str:
        """Create a new session via HTTP API. Returns the session ID."""
        try:
            session = self._api_post("/session", {"title": title or "New session"})
            sid = session.get("id", "")
            logger.info("Session created: %s (%s)", sid, title)
            return sid
        except Exception as e:
            logger.error("Failed to create session: %s", e)
            return ""

    def list_sessions(self, limit: int = 20) -> list:
        """Fetch the session list via HTTP API, sorted by updated time desc."""
        try:
            sessions: List[dict] = self._api_get("/session")
        except Exception as e:
            logger.error("Failed to list sessions: %s", e)
            return []

        sessions.sort(key=lambda s: s.get("time", {}).get("updated", 0), reverse=True)
        return sessions[:limit]

    def _get_recent_session_id(self) -> Optional[str]:
        """Return the ID of the most recently updated session."""
        sessions = self.list_sessions(limit=1)
        return sessions[0].get("id") if sessions else None

    # --- Execution ------------------------------------------------------------

    def execute_async(self, command: str, session_id: Optional[str] = None) -> str:
        """Send a message via `prompt_async` — returns immediately.

        The ``prompt_async`` endpoint returns 204 No Content (not JSON),
        so we don't parse the response body.
        """
        if not self._server_url:
            return ""

        sid = self._resolve_session_id(session_id, command)
        body: Dict[str, Any] = {"parts": [{"type": "text", "text": command}]}
        try:
            if not self.is_serve_running():
                raise RuntimeError("opencode serve is not running")
            requests.post(
                f"{self._server_url}/session/{sid}/prompt_async",
                json=body,
                headers={"Accept": "application/json"},
                timeout=10,
            )
        except Exception as e:
            logger.error("Async execution failed: %s", e)
            return ""
        return sid

    def poll_messages(self, session_id: str, since_id: str = "") -> List[Dict]:
        """Poll a session for new messages since *since_id*.

        Returns a list of message parts (text only).  Each dict has keys
        ``text`` and ``role``.
        """
        if not session_id or not self._server_url:
            return []

        try:
            messages = self._api_get(f"/session/{session_id}/message", timeout=10)
        except Exception:
            return []

        results = []
        found_since = not since_id  # if no since_id, take all
        for msg in messages:
            info = msg.get("info", {})
            mid = info.get("id", "")
            if not found_since:
                if mid == since_id:
                    found_since = True
                continue

            role = info.get("role", "")
            for part in msg.get("parts", []):
                if part.get("type") == "text" and part.get("text"):
                    results.append({"text": part["text"], "role": role})

        # Return only the NEW messages, and track the latest ID
        return results

    def get_session_status(self, session_id: str) -> dict:
        """Quick status check on a session (running/idle)."""
        try:
            info = self._api_get(f"/session/{session_id}", timeout=5)
            return {"id": info.get("id", ""), "status": "active"}
        except Exception:
            return {"id": session_id, "status": "unknown"}

    def execute(
        self, command: str,
        session_id: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> ExecutionResult:
        """Execute a command by sending it to the opencode server via HTTP API.

        *session_id* controls which session to use:
        - ``None`` → continue most recent session
        - ``"__new__"`` → create a fresh session
        - any other string → continue that specific session
        """
        if not self._server_url:
            return ExecutionResult(
                success=False, output="", error="opencode serve not running",
            )

        actual_timeout = timeout or self._config.opencode.command_timeout
        start_time = time.monotonic()

        try:
            # Resolve which session to use
            sid = self._resolve_session_id(session_id, command)

            # Send message via HTTP API
            body: Dict[str, Any] = {
                "parts": [{"type": "text", "text": command}],
            }
            response = self._api_post(
                f"/session/{sid}/message", body, timeout=actual_timeout,
            )

            # Extract text from response parts
            texts: List[str] = []
            for part in response.get("parts", []):
                if part.get("type") == "text" and part.get("text"):
                    texts.append(part["text"])

            output = "\n".join(texts) if texts else "(no output)"
            duration = time.monotonic() - start_time

            return ExecutionResult(
                success=True,
                output=output,
                session_id=sid,
                duration_seconds=duration,
            )

        except requests.Timeout:
            return ExecutionResult(
                success=False, output="",
                error=f"timeout after {actual_timeout}s",
                duration_seconds=time.monotonic() - start_time,
            )
        except Exception as e:
            return ExecutionResult(
                success=False, output="", error=str(e),
                duration_seconds=time.monotonic() - start_time,
            )

    def _resolve_session_id(self, session_id: Optional[str], command: str) -> str:
        """Resolve the session ID based on the session_mode flag.

        - ``"__new__"`` → create a fresh session
        - ``None`` → find the most recent session, or create one
        - otherwise → use the given ID
        """
        if session_id == "__new__":
            sid = self.create_session(title=command[:50])
            return sid or self._get_or_create_fallback(command)

        if session_id:
            return session_id

        # Continue most recent session
        sid = self._get_recent_session_id()
        return sid or self._get_or_create_fallback(command)

    def _get_or_create_fallback(self, command: str) -> str:
        """Last-resort: create a new session."""
        logger.info("No sessions found, creating new one")
        sid = self.create_session(title=command[:50])
        return sid or ""

    # --- Compatibility aliases ------------------------------------------------

    def execute_with_timeout(
        self, command: str,
        timeout: Optional[int] = None,
        session_id: Optional[str] = None,
    ) -> ExecutionResult:
        """Execute with an explicit timeout (overrides config)."""
        return self.execute(command, session_id=session_id, timeout=timeout)
