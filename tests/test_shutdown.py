"""Tests for wechat_opencode.shutdown."""

import signal
import threading

import pytest

from wechat_opencode.shutdown import ShutdownHandler


class TestShutdownHandler:
    def test_initial_state(self):
        handler = ShutdownHandler()
        assert handler.is_shutting_down is False

    def test_trigger_shutdown(self):
        handler = ShutdownHandler()
        called = []
        handler.register(lambda: called.append(True))
        handler.trigger_shutdown()
        assert handler.is_shutting_down is True
        assert len(called) == 1

    def test_trigger_without_callback(self):
        handler = ShutdownHandler()
        handler.trigger_shutdown()
        assert handler.is_shutting_down is True

    def test_shutdown_event_is_set(self):
        handler = ShutdownHandler()
        assert handler.shutdown_event.is_set() is False
        handler.trigger_shutdown()
        assert handler.shutdown_event.is_set() is True
