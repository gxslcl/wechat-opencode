"""Tests for wechat_opencode.config."""

import os
import tempfile
from pathlib import Path

import pytest

from wechat_opencode.config import Config, load_config, OpenCodeConfig, WeChatConfig, ServiceConfig
from wechat_opencode.types import DEFAULT_PREFIX, DEFAULT_SERVE_PORT, MAX_MSG_LEN


class TestLoadConfigDefaults:
    def test_no_config_file_returns_defaults(self):
        config = load_config("/nonexistent/path/config.yaml")
        assert config.opencode.serve_port == DEFAULT_SERVE_PORT
        assert config.wechat.prefix == DEFAULT_PREFIX
        assert config.wechat.max_message_length == MAX_MSG_LEN

    def test_default_config_is_valid(self):
        config = Config()
        assert isinstance(config.opencode, OpenCodeConfig)
        assert isinstance(config.wechat, WeChatConfig)
        assert isinstance(config.service, ServiceConfig)
        assert config.wechat.bot_remark == "机器人"


class TestLoadConfigFromFile:
    def test_full_config(self, tmp_path):
        yaml_content = """
opencode:
  project_dir: "D:/myproject"
  serve_port: 5000
  serve_host: "0.0.0.0"
  command_timeout: 600
  format: "json"
wechat:
  prefix: "/ai"
  filehelper_wxid: "filehelper"
  bot_remark: "mybot"
  max_message_length: 2000
  max_parts: 5
service:
  heartbeat_interval: 60
  auto_restart: false
  log_level: "DEBUG"
  log_file: "test.log"
"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml_content, encoding="utf-8")

        config = load_config(str(config_file))
        assert config.opencode.project_dir == "D:/myproject"
        assert config.opencode.serve_port == 5000
        assert config.wechat.prefix == "/ai"
        assert config.wechat.max_message_length == 2000
        assert config.wechat.bot_remark == "mybot"
        assert config.service.heartbeat_interval == 60
        assert config.service.auto_restart is False
        assert config.service.log_level == "DEBUG"

    def test_partial_config_fills_defaults(self, tmp_path):
        yaml_content = """
opencode:
  serve_port: 5000
"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml_content, encoding="utf-8")

        config = load_config(str(config_file))
        assert config.opencode.serve_port == 5000
        # All other fields should be defaults
        assert config.wechat.prefix == DEFAULT_PREFIX
        assert config.opencode.command_timeout == 300
        assert config.service.auto_restart is True

    def test_empty_yaml_returns_defaults(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("", encoding="utf-8")

        config = load_config(str(config_file))
        assert config.opencode.serve_port == DEFAULT_SERVE_PORT

    def test_env_var_config(self, tmp_path, monkeypatch):
        yaml_content = """
opencode:
  serve_port: 7777
"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml_content, encoding="utf-8")

        monkeypatch.setenv("WOC_CONFIG", str(config_file))
        config = load_config()  # no explicit path
        assert config.opencode.serve_port == 7777

        monkeypatch.delenv("WOC_CONFIG", raising=False)
