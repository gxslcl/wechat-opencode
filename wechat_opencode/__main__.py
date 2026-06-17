"""CLI entry point: python -m wechat_opencode"""

import argparse
import os
import shutil
import sys
from pathlib import Path

import yaml


def _check_opencode() -> bool:
    """Check if opencode CLI is available in PATH."""
    return shutil.which("opencode") is not None or shutil.which("opencode.cmd") is not None


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

    # Pre-flight: check opencode CLI before doing anything
    if not _check_opencode():
        print("❌ opencode CLI 未安装或不在 PATH 中", file=sys.stderr)
        print("   请安装: npm install -g @opencode-ai/cli", file=sys.stderr)
        print("   需要 Node.js 18+", file=sys.stderr)
        sys.exit(1)
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Force run setup wizard",
    )
    args = parser.parse_args()

    from wechat_opencode.config import _find_config_path

    config_path = args.config or str(_find_config_path() or "config.yaml")

    if args.check:
        print("=== 环境检查 ===\n")
        ok = True

        # Node.js
        node = shutil.which("node") or shutil.which("node.exe")
        if node:
            import subprocess
            try:
                ver = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=5).stdout.strip()
                print(f"  ✅ Node.js: {ver} ({node})")
            except Exception:
                print(f"  ✅ Node.js: {node}")
        else:
            print("  ❌ Node.js 未安装 (需要 18+)")
            print("     下载: https://nodejs.org")
            ok = False

        # opencode CLI
        if _check_opencode():
            print("  ✅ opencode CLI: 已安装")
        else:
            print("  ❌ opencode CLI 未安装")
            print("     执行: npm install -g @opencode-ai/cli")
            ok = False

        # Config
        if not _config_valid(config_path):
            print(f"  ❌ config.yaml 缺失或不完整: {config_path}")
            print("     执行: python -m wechat_opencode --setup")
            ok = False
        else:
            from wechat_opencode.config import load_config
            config = load_config(args.config)
            print(f"  ✅ bot_type: {config.bot_type.value}")
            print(f"  ✅ opencode.serve_port: {config.opencode.serve_port}")
            print(f"  ✅ opencode.project_dir: {config.opencode.project_dir}")
            if config.deepseek_api_key:
                print(f"  ✅ deepseek_api_key: 已配置")
            elif os.environ.get("DEEPSEEK_API_KEY"):
                print(f"  ✅ DEEPSEEK_API_KEY: 环境变量已设置")
            else:
                print("  ⚠️ deepseek_api_key: 未设置")
            if config.bot_type.value == "feishu":
                print(f"  ✅ feishu.app_id: {config.feishu.app_id[:10] if config.feishu.app_id else '(空)'}")

        # Python version
        print(f"  ✅ Python: {sys.version.split()[0]}")

        print(f"\n{'✅ 全部通过' if ok else '❌ 存在未通过项，请修复后重试'}")
        sys.exit(0 if ok else 1)

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
    # Ensure DEEPSEEK_API_KEY is available from config.yaml
    if config.deepseek_api_key and not os.environ.get("DEEPSEEK_API_KEY"):
        os.environ["DEEPSEEK_API_KEY"] = config.deepseek_api_key
    app = WeChatOpenCode(config, dry_run=args.dry_run)

    try:
        app.start()
    except KeyboardInterrupt:
        app.stop()


if __name__ == "__main__":
    main()
