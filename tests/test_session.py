"""Tests for wechat_opencode.session."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest
import requests

from wechat_opencode.config import Config
from wechat_opencode.session import OpenCodeSession


@pytest.fixture
def config():
    return Config()


@pytest.fixture
def session(config):
    """Session with server URL set (pretend serve is running)."""
    s = OpenCodeSession(config)
    s._server_url = "http://127.0.0.1:4096"
    return s


@pytest.fixture
def session_running(session):
    """Session with serve process mocked as alive (for API guard checks)."""
    session._serve_process = MagicMock()
    session._serve_process.poll.return_value = None
    return session


# =============================================================================
# Serve lifecycle
# =============================================================================

class TestOpenCodeSessionServe:
    @patch.object(OpenCodeSession, "_kill_port_occupant")
    @patch("wechat_opencode.session.subprocess.Popen")
    @patch("wechat_opencode.session.socket.create_connection")
    @patch.object(OpenCodeSession, "_wait_for_api_ready", return_value=True)
    def test_start_serve_launches_process(self, mock_api, mock_socket, mock_popen, mock_kill, session):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc
        url = session.start_serve()
        assert url == "http://127.0.0.1:4096"
        mock_popen.assert_called_once()
        cmd = mock_popen.call_args[0][0]
        assert any("opencode" in part.lower() for part in cmd)
        assert "serve" in cmd

    @patch.object(OpenCodeSession, "_kill_port_occupant")
    @patch("wechat_opencode.session.subprocess.Popen")
    def test_start_serve_raises_if_process_dies(self, mock_popen, mock_kill, session):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1
        mock_popen.return_value = mock_proc
        with pytest.raises(RuntimeError, match="exited unexpectedly"):
            session.start_serve()

    def test_stop_serve_terminates_process(self, session):
        mock_proc = MagicMock()
        mock_proc.wait.return_value = 0
        session._serve_process = mock_proc
        session.stop_serve()
        mock_proc.terminate.assert_called_once()

    def test_stop_serve_kills_on_timeout(self, session):
        mock_proc = MagicMock()
        mock_proc.wait.side_effect = [subprocess.TimeoutExpired("cmd", 5), None]
        session._serve_process = mock_proc
        session.stop_serve()
        mock_proc.terminate.assert_called_once()
        mock_proc.kill.assert_called_once()

    def test_is_serve_running(self, session):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        session._serve_process = mock_proc
        assert session.is_serve_running() is True
        mock_proc.poll.return_value = 1
        assert session.is_serve_running() is False

    def test_is_serve_running_no_process(self, session):
        assert session.is_serve_running() is False


# =============================================================================
# Session management (HTTP API)
# =============================================================================

TEXT_PART = {"type": "text", "text": "Hello!"}
API_RESPONSE = {"parts": [{"type": "step-start"}, TEXT_PART, {"type": "step-finish"}]}
RECENT_SESSION = [{"id": "ses_latest", "time": {"updated": 999}}]


def _mock_resp(data):
    r = MagicMock()
    r.json.return_value = data
    return r


class TestSessionManagement:
    @patch("requests.get")
    def test_list_sessions(self, mock_get, session_running):
        mock_get.return_value = _mock_resp([
            {"id": "s1", "time": {"updated": 300}},
            {"id": "s2", "time": {"updated": 100}},
        ])
        sessions = session_running.list_sessions()
        assert sessions[0]["id"] == "s1"

    @patch("requests.post")
    def test_create_session(self, mock_post, session_running):
        mock_post.return_value = _mock_resp({"id": "new_sid"})
        assert session_running.create_session("T") == "new_sid"

    @patch("requests.get")
    def test_get_recent_session_id(self, mock_get, session_running):
        mock_get.return_value = _mock_resp(RECENT_SESSION)
        assert session_running._get_recent_session_id() == "ses_latest"

    @patch("requests.get")
    def test_get_recent_session_id_empty(self, mock_get, session_running):
        mock_get.return_value = _mock_resp([])
        assert session_running._get_recent_session_id() is None


# =============================================================================
# Execution (HTTP API)
# =============================================================================

class TestExecute:
    def test_execute_success(self, session_running):
        with patch.object(session_running, "_get_recent_session_id", return_value="ses_abc"), \
             patch.object(session_running, "_api_post", return_value=API_RESPONSE):
            r = session_running.execute("hello")
            assert r.success is True
            assert r.output == "Hello!"

    def test_execute_new_session(self, session_running):
        with patch.object(session_running, "create_session", return_value="ses_new"), \
             patch.object(session_running, "_api_post", return_value=API_RESPONSE):
            r = session_running.execute("hello", session_id="__new__")
            assert r.success is True

    def test_execute_no_server(self, session):
        session._server_url = ""
        r = session.execute("hello")  # uses session (no serve mock)
        assert r.success is False

    def test_execute_timeout(self, session_running):
        with patch.object(session_running, "_get_recent_session_id", return_value="ses_abc"), \
             patch.object(session_running, "_api_post", side_effect=requests.Timeout()):
            r = session_running.execute("hello")
            assert r.success is False

    def test_execute_empty_response(self, session_running):
        with patch.object(session_running, "_get_recent_session_id", return_value="ses_abc"), \
             patch.object(session_running, "_api_post", return_value={"parts": []}):
            r = session_running.execute("hello")
            assert r.output == "(no output)"

    def test_execute_non_text_parts(self, session_running):
        with patch.object(session_running, "_get_recent_session_id", return_value="ses_abc"), \
             patch.object(session_running, "_api_post", return_value={
                 "parts": [{"type": "step-start"}, {"type": "tool_use"}],
             }):
            r = session_running.execute("hello")
            assert r.output == "(no output)"

    def test_execute_multiple_text_parts(self, session_running):
        with patch.object(session_running, "_get_recent_session_id", return_value="ses_abc"), \
             patch.object(session_running, "_api_post", return_value={
                 "parts": [{"type": "text", "text": "Line1"}, {"type": "text", "text": "Line2"}],
             }):
            r = session_running.execute("hello")
            assert r.output == "Line1\nLine2"

    def test_execute_with_timeout(self, session_running):
        with patch.object(session_running, "_get_recent_session_id", return_value="ses_abc"), \
             patch.object(session_running, "_api_post", return_value=API_RESPONSE) as mock_post:
            r = session_running.execute_with_timeout("hello", timeout=60)
            assert r.success is True
            assert mock_post.call_args[1]["timeout"] == 60
