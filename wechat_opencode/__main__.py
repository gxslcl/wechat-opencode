"""CLI entry point: python -m wechat_opencode"""

import argparse
import os
import sys
from pathlib import Path

import yaml


def _config_valid(config_path: str) -> bool:
    """Check if config exists and has required fields."""
    if not os.path.exists(config_path):
        return False
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        return False
    if data.get("bot_type") == "feishu":
        feishu = data.get("feishu", {})
        return bool(feishu.get("app_id") and feishu.get("app_secret"))
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="wechat_opencode",
        description="WeChat remote control bridge for OpenCode CLI",
    )
    parser.add_argument(
        "--config", "-c",
        help="Path to config.yaml (default: ./config.yaml)",
        default=None,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Start without connecting to WeChat (for testing)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run health checks and exit",
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Force run setup wizard",
    )
    args = parser.parse_args()

    from wechat_opencode.config import _find_config_path

    config_path = args.config or str(_find_config_path() or "config.yaml")

    if args.check:
        print("Checking configuration...")
        if not _config_valid(config_path):
            print(f"  ❌ config.yaml missing or incomplete at: {config_path}")
            print("  Run with --setup to configure.")
            sys.exit(1)
        from wechat_opencode.config import load_config
        config = load_config(args.config)
        print(f"  ✅ bot_type: {config.bot_type.value}")
        print(f"  ✅ opencode.serve_port: {config.opencode.serve_port}")
        print(f"  ✅ opencode.project_dir: {config.opencode.project_dir}")
        if config.bot_type.value == "feishu":
            print(f"  ✅ feishu.app_id: {config.feishu.app_id[:10]}...")
        print("All checks passed.")
        sys.exit(0)

    # Setup wizard: first run or forced
    if args.setup or not _config_valid(config_path):
        if not _config_valid(config_path) and not args.setup:
            print("🔧 首次运行 — 启动配置向导...")
        from wechat_opencode.setup_wizard import run_setup
        run_setup(config_path)
        if not _config_valid(config_path):
            print("❌ 配置未完成，退出。重新运行以再次配置。")
            sys.exit(1)
        print("✅ 配置完成，启动服务...")

    # Import here to avoid heavy imports on --check/--help
    from wechat_opencode.core import WeChatOpenCode
    from wechat_opencode.config import load_config

    config = load_config(args.config)
    app = WeChatOpenCode(config, dry_run=args.dry_run)

    try:
        app.start()
    except KeyboardInterrupt:
        app.stop()


if __name__ == "__main__":
    main()
