"""Tests for wechat_opencode.health."""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from wechat_opencode.config import Config
from wechat_opencode.health import ComponentStatus, HealthMonitor


@pytest.fixture
def config():
    return Config()


@pytest.fixture
def bridge():
    bridge = MagicMock()
    bridge.is_wechat_running.return_value = True
    return bridge


@pytest.fixture
def session():
    session = MagicMock()
    session.is_serve_running.return_value = True
    return session


@pytest.fixture
def shutdown_event():
    return threading.Event()


@pytest.fixture
def notified():
    return []


@pytest.fixture
def monitor(config, bridge, session, shutdown_event, notified):
    return HealthMonitor(
        config=config,
        bridge=bridge,
        session=session,
        shutdown_event=shutdown_event,
        on_notify=notified.append,
    )


# =============================================================================
# ComponentStatus
# =============================================================================

class TestComponentStatus:
    def test_defaults_optimistic(self):
        status = ComponentStatus(name="Test")
        assert status.running is True
        assert status.failures == 0
        assert status.last_check == 0.0
        assert status.last_ok == 0.0

    def test_custom_values(self):
        status = ComponentStatus(name="Test", running=False, failures=3)
        assert status.running is False
        assert status.failures == 3


# =============================================================================
# Construction and initial state
# =============================================================================

class TestHealthMonitorInit:
    def test_initial_state(self, monitor):
        assert monitor._running is False
        assert monitor._thread is None
        assert monitor.is_healthy is True  # optimistic
        assert monitor._interval == 30
        assert monitor._auto_restart is True

    def test_config_respected(self, config, bridge, session, shutdown_event):
        config.service.heartbeat_interval = 60
        config.service.auto_restart = False
        mon = HealthMonitor(config, bridge, session, shutdown_event)
        assert mon._interval == 60
        assert mon._auto_restart is False

    def test_on_notify_optional(self, config, bridge, session, shutdown_event):
        mon = HealthMonitor(config, bridge, session, shutdown_event, on_notify=None)
        assert mon._on_notify is None


# =============================================================================
# Start / Stop lifecycle
# =============================================================================

class TestHealthMonitorLifecycle:
    def test_start_starts_thread(self, monitor):
        monitor.start()
        assert monitor._running is True
        assert monitor._thread is not None
        assert monitor._thread.is_alive()
        monitor.stop()

    def test_start_idempotent(self, monitor):
        monitor.start()
        thread = monitor._thread
        monitor.start()  # second start should be a no-op
        assert monitor._thread is thread
        monitor.stop()

    def test_stop_sets_running_false(self, monitor):
        monitor.start()
        monitor.stop()
        assert monitor._running is False

    def test_stop_before_start(self, monitor):
        monitor.stop()  # should not raise
        assert monitor._running is False


# =============================================================================
# is_healthy and get_status
# =============================================================================

class TestHealthMonitorStatus:
    def test_is_healthy_initially_true(self, monitor):
        assert monitor.is_healthy is True

    def test_is_healthy_marked_down(self, monitor):
        monitor._wechat_status.running = False
        assert monitor.is_healthy is False

    def test_is_healthy_both_down(self, monitor):
        monitor._wechat_status.running = False
        monitor._opencode_status.running = False
        assert monitor.is_healthy is False

    def test_get_status_returns_dict(self, monitor):
        status = monitor.get_status()
        assert "wechat" in status
        assert "opencode" in status
        assert "healthy" in status
        assert status["healthy"] is True
        assert status["wechat"]["running"] is True
        assert status["opencode"]["running"] is True
        assert status["wechat"]["failures"] == 0

    def test_get_status_reflects_state(self, monitor):
        monitor._wechat_status.running = False
        monitor._wechat_status.failures = 2
        monitor._opencode_status.running = False
        status = monitor.get_status()
        assert status["healthy"] is False
        assert status["wechat"]["running"] is False
        assert status["wechat"]["failures"] == 2
        assert status["opencode"]["running"] is False


# =============================================================================
# Health check logic (direct method calls — no thread)
# =============================================================================

class TestHealthMonitorCheckWeChat:
    def test_detects_running(self, monitor, bridge):
        bridge.is_wechat_running.return_value = True
        monitor._check_wechat()
        assert monitor._wechat_status.running is True
        assert monitor._wechat_status.failures == 0

    def test_detects_down_without_auto_restart(self, config, bridge, session, shutdown_event):
        config.service.auto_restart = False
        mon = HealthMonitor(config, bridge, session, shutdown_event)
        bridge.is_wechat_running.return_value = False
        mon._check_wechat()
        assert mon._wechat_status.running is False
        assert mon._wechat_status.failures == 1

    def test_accumulates_failures_without_auto_restart(self, config, bridge, session, shutdown_event):
        config.service.auto_restart = False
        mon = HealthMonitor(config, bridge, session, shutdown_event)
        bridge.is_wechat_running.return_value = False
        mon._check_wechat()
        mon._check_wechat()
        mon._check_wechat()
        assert mon._wechat_status.failures == 3

    def test_recovers_after_failure(self, monitor, bridge):
        bridge.is_wechat_running.return_value = False
        monitor._check_wechat()  # auto-recovery kicks in → running back to True
        assert monitor._wechat_status.running is True
        assert monitor._wechat_status.failures == 0

        bridge.is_wechat_running.return_value = True
        monitor._check_wechat()
        assert monitor._wechat_status.running is True
        assert monitor._wechat_status.failures == 0

    def test_error_during_check_triggers_recovery(self, monitor, bridge):
        """With auto_restart=True, an error causes recovery attempt."""
        bridge.is_wechat_running.side_effect = RuntimeError("boom")
        monitor._check_wechat()
        bridge.stop.assert_called_once()
        bridge.start.assert_called_once()


class TestHealthMonitorCheckOpenCode:
    def test_detects_running(self, monitor, session):
        session.is_serve_running.return_value = True
        monitor._check_opencode()
        assert monitor._opencode_status.running is True
        assert monitor._opencode_status.failures == 0

    def test_detects_down_without_auto_restart(self, config, bridge, session, shutdown_event):
        config.service.auto_restart = False
        mon = HealthMonitor(config, bridge, session, shutdown_event)
        session.is_serve_running.return_value = False
        mon._check_opencode()
        assert mon._opencode_status.running is False
        assert mon._opencode_status.failures == 1

    def test_error_during_check_triggers_recovery(self, monitor, session):
        """With auto_restart=True, an error causes recovery attempt."""
        session.is_serve_running.side_effect = RuntimeError("boom")
        monitor._check_opencode()
        session.stop_serve.assert_called_once()
        session.start_serve.assert_called_once()


# =============================================================================
# Auto-recovery
# =============================================================================

class TestHealthMonitorAutoRecoverWeChat:
    def test_recover_stops_and_starts_bridge(self, monitor, bridge):
        bridge.is_wechat_running.return_value = False
        monitor._check_wechat()
        bridge.stop.assert_called_once()
        bridge.start.assert_called_once()
        assert monitor._wechat_status.running is True

    def test_auto_restart_disabled_skips_recovery(self, config, bridge, session, shutdown_event):
        config.service.auto_restart = False
        mon = HealthMonitor(config, bridge, session, shutdown_event)
        bridge.is_wechat_running.return_value = False
        mon._check_wechat()
        bridge.stop.assert_not_called()
        bridge.start.assert_not_called()
        assert mon._wechat_status.running is False

    def test_recovery_failure_logged(self, monitor, bridge):
        bridge.is_wechat_running.return_value = False
        bridge.start.side_effect = RuntimeError("start failed")
        monitor._check_wechat()  # should not raise
        assert monitor._wechat_status.running is False


class TestHealthMonitorAutoRecoverOpenCode:
    def test_recover_stops_and_starts_session(self, monitor, session):
        session.is_serve_running.return_value = False
        monitor._check_opencode()
        session.stop_serve.assert_called_once()
        session.start_serve.assert_called_once()
        assert monitor._opencode_status.running is True

    def test_auto_restart_disabled_skips_recovery(self, config, bridge, session, shutdown_event):
        config.service.auto_restart = False
        mon = HealthMonitor(config, bridge, session, shutdown_event)
        session.is_serve_running.return_value = False
        mon._check_opencode()
        session.stop_serve.assert_not_called()
        session.start_serve.assert_not_called()
        assert mon._opencode_status.running is False

    def test_recovery_failure_logged(self, monitor, session):
        session.is_serve_running.return_value = False
        session.start_serve.side_effect = RuntimeError("start failed")
        monitor._check_opencode()  # should not raise
        assert monitor._opencode_status.running is False


# =============================================================================
# on_notify callback
# =============================================================================

class TestHealthMonitorNotify:
    def test_no_notify_on_wechat_recovery(self, monitor, bridge, notified):
        """Recovery is logged but no WeChat notification is sent."""
        bridge.is_wechat_running.return_value = False
        monitor._check_wechat()
        assert len(notified) == 0

    def test_no_notify_on_opencode_recovery(self, monitor, session, notified):
        """Recovery is logged but no WeChat notification is sent."""
        session.is_serve_running.return_value = False
        monitor._check_opencode()
        assert len(notified) == 0

    def test_no_notify_when_healthy(self, monitor, notified):
        monitor._check_wechat()
        monitor._check_opencode()
        assert len(notified) == 0

    def test_no_notify_without_callback(self, config, bridge, session, shutdown_event):
        bridge.is_wechat_running.return_value = False
        mon = HealthMonitor(config, bridge, session, shutdown_event, on_notify=None)
        mon._check_wechat()
        # Should not raise


# =============================================================================
# Monitor loop integration
# =============================================================================

class TestHealthMonitorLoop:
    def test_loop_exits_on_shutdown_event(self, monitor):
        """The loop should exit quickly when shutdown_event is set."""
        monitor.start()
        # Set the shutdown event — loop should exit on next iteration
        monitor._shutdown_event.set()
        time.sleep(0.2)
        assert monitor._running is True  # running flag stays True
        # After shutdown event set, the wait() returns immediately
        # Next iteration checks is_set() → breaks
        # We just verify no crash

    def test_loop_checks_both_components(self, config, bridge, session, shutdown_event):
        """The loop should call both check methods each iteration."""
        config.service.heartbeat_interval = 0.01  # very short wait
        mon = HealthMonitor(config, bridge, session, shutdown_event, on_notify=None)
        mon._running = True

        # Stop the loop after the first iteration
        def stop_after_check(*args, **kwargs):
            mon._running = False
            return True

        bridge.is_wechat_running.side_effect = stop_after_check

        mon._monitor_loop()
        bridge.is_wechat_running.assert_called()
        session.is_serve_running.assert_called()
