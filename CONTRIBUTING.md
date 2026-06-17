# Contributing to WeChat-OpenCode

Thank you for considering contributing to WeChat-OpenCode! This document outlines the process.

## Development Setup

```bash
git clone https://github.com/yourname/wechat-opencode.git
cd wechat-opencode
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Code Style

- Follow PEP 8 where possible
- Use type hints for function signatures
- Keep functions focused and small (< 50 lines preferred)
- Write Chinese comments for business logic (Chinese-speaking team)

## Testing

```bash
# Run all tests
pytest tests/

# Run with coverage
pytest tests/ --cov=wechat_opencode --cov-report=term

# Run specific test file
pytest tests/test_core.py -v
```

## Pull Request Process

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Make your changes
4. Run tests (`pytest tests/ -x`)
5. Commit with a clear message
6. Push and create a PR

## Project Structure

```
wechat_opencode/          # Main package
  ├── core.py             # Main application loop
  ├── feishu_bot.py       # Feishu bot (WebSocket + API)
  ├── intent_router.py    # 3-layer intent analysis
  ├── worker.py           # Worker manager (task execution)
  ├── bus.py              # Message bus (pub/sub)
  ├── session.py          # OpenCode session management
  ├── commands/           # /-command handlers
  ├── web_ui.py           # Web admin panel
  └── ...
tests/                    # Test suite (141+ tests)
config.example.yaml       # Configuration template
```

## Architecture Notes

- **Supervisor** (port 4097): Chat agent, never restarts
- **Worker** (port 4098): Execution agent, can restart independently
- **MessageBus**: All messages flow through bus (Feishu + Web UI in sync)
- **TAG Protocol**: `[TASK:]`, `[结果:]`, `[FILE:]` — text-based inter-agent communication

## Questions?

Open an issue on GitHub.
