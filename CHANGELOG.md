# Changelog

## [0.1.0] - 2026-06-16

### Added
- Initial open-source release
- Feishu bot with WebSocket long connection (lark-oapi)
- 3-layer intent analysis (/prefix → keyword → LLM)
- 24 slash commands (screen, file, window, ppt, cron, etc.)
- Supervisor + Worker dual `opencode serve` architecture (ports 4097/4098)
- TAG protocol for inter-agent communication
- Chinese natural language cron (`每天 09:00`, `每30分钟`)
- Message bus for synchronized Feishu + Web UI
- Self-healing: auto-retry ×3, git rollback, watchdog, hot reload
- Context compaction (auto after 1h idle + 300+ messages; manual via `/compact`)
- Web admin panel (port 8080) + config wizard (port 8099)
- Time-windowed message dedup + rate limiting
- 141 unit tests
