"""Configuration loading and validation for wechat_opencode."""

import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

import yaml

from wechat_opencode.types import (
    DEFAULT_HEARTBEAT_INTERVAL,
    DEFAULT_PREFIX,
    DEFAULT_SERVE_PORT,
    DEFAULT_TIMEOUT,
    MAX_MSG_LEN,
    MAX_PARTS,
)


class BotType(Enum):
    """Which bot backend to use."""
    WECHAT = "wechat"
    FEISHU = "feishu"


@dataclass
class OpenCodeConfig:
    """OpenCode CLI configuration."""
    project_dir: str = field(default_factory=lambda: str(Path.home()))
    serve_port: int = DEFAULT_SERVE_PORT
    worker_serve_port: int = 4098
    serve_host: str = "127.0.0.1"
    command_timeout: int = DEFAULT_TIMEOUT
    format: str = "default"


@dataclass
class WeChatConfig:
    """WeChat-specific configuration."""
    prefix: str = DEFAULT_PREFIX
    filehelper_wxid: str = "filehelper"
    bot_remark: str = "机器人"
    max_message_length: int = MAX_MSG_LEN
    max_parts: int = MAX_PARTS


@dataclass
class FeishuConfig:
    """Feishu (飞书) bot configuration."""
    app_id: str = ""
    app_secret: str = ""


@dataclass
class ServiceConfig:
    """Service lifecycle configuration."""
    heartbeat_interval: int = DEFAULT_HEARTBEAT_INTERVAL
    auto_restart: bool = True
    log_level: str = "INFO"
    log_file: str = "wechat_opencode.log"


@dataclass
class Config:
    """Top-level configuration."""
    bot_type: BotType = BotType.WECHAT
    opencode: OpenCodeConfig = field(default_factory=OpenCodeConfig)
    wechat: WeChatConfig = field(default_factory=WeChatConfig)
    feishu: FeishuConfig = field(default_factory=FeishuConfig)
    service: ServiceConfig = field(default_factory=ServiceConfig)


def _dict_to_config(d: dict) -> Config:
    """Convert a nested dict to Config, filling defaults for missing keys."""
    oc = d.get("opencode", {})
    wc = d.get("wechat", {})
    fs = d.get("feishu", {})
    svc = d.get("service", {})

    # Parse bot_type
    raw_type = d.get("bot_type", "wechat")
    try:
        bot_type = BotType(raw_type)
    except ValueError:
        bot_type = BotType.WECHAT

    return Config(
        bot_type=bot_type,
        opencode=OpenCodeConfig(
            project_dir=oc.get("project_dir", str(Path.home())),
            serve_port=oc.get("serve_port", DEFAULT_SERVE_PORT),
            worker_serve_port=oc.get("worker_serve_port", 4098),
            serve_host=oc.get("serve_host", "127.0.0.1"),
            command_timeout=oc.get("command_timeout", DEFAULT_TIMEOUT),
            format=oc.get("format", "default"),
        ),
        wechat=WeChatConfig(
            prefix=wc.get("prefix", DEFAULT_PREFIX),
            filehelper_wxid=wc.get("filehelper_wxid", "filehelper"),
            bot_remark=wc.get("bot_remark", "机器人"),
            max_message_length=wc.get("max_message_length", MAX_MSG_LEN),
            max_parts=wc.get("max_parts", MAX_PARTS),
        ),
        feishu=FeishuConfig(
            app_id=fs.get("app_id", ""),
            app_secret=fs.get("app_secret", ""),
        ),
        service=ServiceConfig(
            heartbeat_interval=svc.get("heartbeat_interval", DEFAULT_HEARTBEAT_INTERVAL),
            auto_restart=svc.get("auto_restart", True),
            log_level=svc.get("log_level", "INFO"),
            log_file=svc.get("log_file", "wechat_opencode.log"),
        ),
    )


def _find_config_path(explicit_path: Optional[str] = None) -> Optional[Path]:
    """Resolve config file path: CLI arg > env var > ./config.yaml > None."""
    if explicit_path:
        p = Path(explicit_path)
        if p.exists():
            return p
        return None  # explicit path given but not found → use defaults

    env_path = os.environ.get("WOC_CONFIG")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p

    local = Path("config.yaml")
    if local.exists():
        return local

    return None


def load_config(path: Optional[str] = None) -> Config:
    """Load configuration from YAML file, falling back to defaults.

    Search order: explicit path > WOC_CONFIG env var > ./config.yaml > all defaults.
    Missing fields in YAML are filled with default values.
    """
    config_path = _find_config_path(path)
    if config_path is None:
        return Config()  # pure defaults

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if data is None:
        return Config()  # empty YAML file

    return _dict_to_config(data)
