"""File transfer — direct search + LLM fallback for /file commands.

Two-layer architecture:
  Layer 1 — direct_search(): glob + fuzzy filename match (milliseconds)
  Layer 2 — ask_supervisor_llm(): prompt the OpenCode supervisor to find files
"""

import logging
import os
import re
import time
from difflib import SequenceMatcher
from typing import List, Optional, Set, Tuple

from wechat_opencode.types import FileCandidate, FileSelectionState

logger = logging.getLogger(__name__)

# --- Search limits ---
_MAX_SCAN_FILES = 8000   # stop searching after this many files
_MAX_DEPTH = 5           # max directory depth from project_dir
_MAX_CANDIDATES = 10     # max results returned

# --- Chinese → English keyword mapping for file name expansion ---
# When a user types a Chinese term, try matching English equivalents.
_KEYWORD_MAP: dict = {
    "配置": ["config", "settings", ".env", "env", "options", "preferences"],
    "设置": ["config", "settings", ".env", "env", "options", "preferences"],
    "日志": ["log", "logger", "logging"],
    "测试": ["test", "tests", "spec", "testing"],
    "文档": ["doc", "docs", "document", "readme", "README"],
    "说明": ["readme", "README", "doc", "docs", "guide"],
    "接口": ["api", "router", "route", "handler", "controller"],
    "路由": ["router", "route", "urls", "routes"],
    "模型": ["model", "models", "schema", "entity"],
    "视图": ["view", "views", "page", "pages", "template", "ui"],
    "前端": ["ui", "template", "templates", "static", "pages", "components", "app"],
    "后端": ["api", "server", "service", "handler", "controller", "app"],
    "数据库": ["db", "database", "sql", "migration", "schema", "repository"],
    "脚本": ["script", "scripts", "run", "start", "build", "deploy"],
    "工具": ["util", "utils", "tool", "tools", "helper", "helpers"],
    "核心": ["core", "main", "index", "app"],
    "入口": ["main", "index", "app", "entry", "start"],
    "启动": ["start", "run", "main", "index", "app", "launch"],
    "依赖": ["requirements", "package", "packages", "dependency"],
    "版本": ["version", "changelog", "CHANGELOG", "release"],
    "任务": ["task", "tasks", "job", "jobs", "queue"],
    "队列": ["queue", "task", "jobs", "worker"],
    "会话": ["session", "sessions"],
    "类型": ["type", "types", "model", "models", "schema"],
    "常量": ["const", "constant", "constants", "types"],
    "错误": ["error", "errors", "exception", "exceptions", "handler"],
    "截图": ["screenshot", "screen", "capture", "image", "img"],
    "图片": ["image", "img", "icon", "icons", "assets", "static"],
    "样式": ["style", "styles", "css", "theme", "themes"],
    "布局": ["layout", "layouts", "template", "templates"],
    "健康": ["health", "status", "ping", "monitor"],
    "监控": ["monitor", "health", "watch", "watcher"],
    "撤销": ["undo", "revert", "rollback"],
    "权限": ["permission", "permissions", "auth", "authorization", "role"],
    "费用": ["cost", "costs", "billing", "price", "usage"],
    "队列": ["queue", "execution", "executor"],
    "自动": ["auto", "reload", "watcher", "watch"],
    "注入": ["inject", "injector", "context"],
    "提醒": ["notify", "notification", "alert", "reminder"],
    "通知": ["notify", "notification", "alert", "reminder"],
    "飞书": ["feishu", "lark", "bot"],
    "微信": ["wechat", "bot", "bridge"],
}

# Sensitive patterns — skip these files to avoid leaking secrets
_SENSITIVE_PATTERNS = [
    r"\.env$", r"\.env\.", r"secret", r"private[._-]?key", r"\.pem$",
    r"\.key$", r"credentials", r"password", r"token",
]


def _is_sensitive(path: str) -> bool:
    """Check if a file path matches sensitive patterns."""
    name = os.path.basename(path).lower()
    return any(re.search(pat, name) for pat in _SENSITIVE_PATTERNS)


def _similarity(a: str, b: str) -> float:
    """Return a 0–1 similarity score between two strings."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _extract_keywords(query: str) -> List[str]:
    """Extract Chinese keywords from query and expand to English patterns."""
    keywords: List[str] = []
    # Check each keyword map entry
    for cn, en_list in _KEYWORD_MAP.items():
        if cn in query:
            keywords.extend(en_list)
    return list(dict.fromkeys(keywords))  # dedup, preserve order


def _get_file_info(filepath: str) -> Tuple[int, float]:
    """Get file size and modification time. Returns (0, 0) on error."""
    try:
        stat = os.stat(filepath)
        return stat.st_size, stat.st_mtime
    except OSError:
        return 0, 0.0


def _is_skip_dir(dirname: str) -> bool:
    """Check if a directory should be skipped during search."""
    return dirname in (
        ".git", "__pycache__", ".venv", "node_modules",
        ".playwright-mcp", ".sisyphus", ".pytest_cache",
        ".mypy_cache", ".tox", ".eggs", "build", "dist",
        ".idea", ".vscode", "AppData", "Application Data",
        "NTUSER.DAT", "PrintHood", "NetHood", "Recent",
        "SendTo", "Cookies", "Start Menu", "Templates",
        "MicrosoftEdge", "Microsoft", "Windows", "Package Cache",
    ) or dirname.startswith(".")


def _scandir_search(
    root: str, patterns: Set[str], max_depth: int,
) -> List[FileCandidate]:
    """Walk the directory tree with depth limit, matching against patterns.

    Uses os.scandir for efficiency. Stops when _MAX_SCAN_FILES is reached.
    Returns candidates sorted by similarity (desc), then mtime (desc).
    """
    candidates: dict = {}  # path -> FileCandidate
    scanned = 0
    start_time = time.monotonic()

    # Normalize patterns to lowercase for case-insensitive matching
    lower_patterns = {p.lower() for p in patterns}

    try:
        for entry in os.scandir(root):
            if scanned >= _MAX_SCAN_FILES:
                logger.debug("Scan limit reached (%d files)", _MAX_SCAN_FILES)
                break

            if time.monotonic() - start_time > 10:
                logger.debug("Scan timeout (10s)")
                break

            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                continue

            if is_dir:
                if _is_skip_dir(entry.name):
                    continue
                if max_depth > 1:
                    try:
                        sub_results = _scandir_search(
                            entry.path, patterns, max_depth - 1,
                        )
                    except (PermissionError, OSError):
                        continue
                    for c in sub_results:
                        if c.path not in candidates:
                            candidates[c.path] = c
                    scanned += 1
                continue

            # It's a file
            scanned += 1
            name_lower = entry.name.lower()

            # Check if filename contains any pattern as substring
            matched = False
            match_score = 0.0
            for pat in lower_patterns:
                if pat in name_lower:
                    matched = True
                    # Score: longer pattern relative to filename = better match
                    match_score = max(match_score, len(pat) / max(len(name_lower), 1))
                    break

            if not matched:
                continue

            # Skip sensitive files and common non-project dirs
            if _is_sensitive(entry.path):
                continue

            try:
                size = entry.stat().st_size
                mtime = entry.stat().st_mtime
            except OSError:
                size, mtime = 0, 0.0

            candidates[entry.path] = FileCandidate(
                path=entry.path, name=entry.name,
                size=size, modified=mtime, similarity=match_score,
            )

    except (PermissionError, OSError) as e:
        logger.debug("Skipping %s: %s", root, e)

    elapsed = time.monotonic() - start_time
    if elapsed > 1:
        logger.debug("Scanned %s: %d files in %.1fs, %d matches",
                      os.path.basename(root), scanned, elapsed, len(candidates))

    # Sort and limit
    result = sorted(
        candidates.values(),
        key=lambda c: (c.similarity, c.modified),
        reverse=True,
    )
    return result[:_MAX_CANDIDATES]


def direct_search(query: str, project_dir: str, max_results: int = _MAX_CANDIDATES) -> List[FileCandidate]:
    """Layer 1 — fast local file search with depth limit.

    Strategies (tried in order until results found):
      1. Exact path relative to project_dir
      2. Build search patterns from query + Chinese keyword expansion
      3. Walk directory tree with depth limit (_MAX_DEPTH)

    Returns candidates sorted by similarity (desc), then modification time.
    """
    search_query = query.strip()
    if not search_query:
        return []

    candidates: dict = {}  # path -> FileCandidate

    # --- Strategy 1: Exact path ---
    exact_path = os.path.join(project_dir, search_query)
    try:
        if os.path.isfile(exact_path) and not _is_sensitive(exact_path):
            size, mtime = _get_file_info(exact_path)
            candidates[exact_path] = FileCandidate(
                path=exact_path, name=os.path.basename(exact_path),
                size=size, modified=mtime, similarity=1.0,
            )
    except OSError:
        pass

    # --- Strategy 2: Build search patterns ---
    # Use the original query + Chinese keyword expansions
    # Don't split into parts — short words match too many unrelated files
    patterns: Set[str] = set()
    patterns.add(search_query)

    # Chinese keyword expansion
    keywords = _extract_keywords(search_query)
    for kw in keywords:
        patterns.add(kw)

    logger.info("Search patterns for '%s': %s", search_query, patterns)

    # --- Strategy 3: Walk directory tree ---
    try:
        found = _scandir_search(project_dir, patterns, _MAX_DEPTH)
    except Exception as e:
        logger.error("Directory scan failed: %s", e)
        found = []

    for c in found:
        if c.path not in candidates:
            # Recalculate similarity against original query
            c.similarity = _similarity(search_query, c.name)
            # Boost score for meaningful pattern matches (≥4 chars or the full query)
            name_lower = c.name.lower()
            for pat in patterns:
                if len(pat) < 4 and pat != search_query:
                    continue  # skip short generic terms like "file", "doc"
                if pat.lower() in name_lower:
                    c.similarity = max(c.similarity, 0.6)
            candidates[c.path] = c

    # Sort: similarity desc, then modification time desc
    result = sorted(
        candidates.values(),
        key=lambda c: (c.similarity, c.modified),
        reverse=True,
    )
    # Filter out very low similarity matches
    result = [c for c in result if c.similarity >= 0.2]
    result = result[:max_results]

    # If the query exactly matches a filename, promote that file to the top
    query_lower = search_query.lower()
    for i, c in enumerate(result):
        if c.name.lower() == query_lower or c.name.lower().startswith(query_lower + "."):
            # Move exact match to front with similarity=1.0
            exact = c
            exact.similarity = 1.0
            result.pop(i)
            result.insert(0, exact)
            break

    return result


def format_candidates(candidates: List[FileCandidate]) -> str:
    """Format a list of file candidates for display to user."""
    if not candidates:
        return ""

    lines = [f"🔍 找到 {len(candidates)} 个可能文件："]
    for i, c in enumerate(candidates, 1):
        try:
            rel_path = os.path.relpath(c.path, os.getcwd())
        except ValueError:
            rel_path = c.path
        # Truncate long paths
        display = rel_path if len(rel_path) <= 60 else "..." + rel_path[-57:]
        size_kb = c.size / 1024
        size_str = f"{size_kb:.1f}KB" if size_kb < 1024 else f"{size_kb / 1024:.1f}MB"
        lines.append(f"  {i}. {display} ({size_str})")
    lines.append("")
    lines.append("回复编号选择文件，或回复 'c' 取消")
    return "\n".join(lines)


def build_llm_prompt(query: str, project_dir: str) -> str:
    """Build a prompt for the supervisor LLM to find files.

    The LLM is expected to use glob/grep tools to search, then reply with:
      [FILE: <完整路径>]   — single match found
      [FILES: 路径1, 路径2, ...]  — multiple candidates
      [NONE]  — nothing found
    """
    return (
        f"用户想获取文件: \"{query}\"\n\n"
        f"工作目录: {project_dir}\n\n"
        "请在以上目录中搜索匹配的文件。注意：\n"
        "1. 先用 glob 工具搜索文件名\n"
        "2. 如果文件名搜索不到，用 grep 搜索文件内容中的关键字\n"
        "3. 排除 .git, __pycache__, .venv, node_modules 等无关目录\n"
        "4. 如果找到明确的文件，回复 [FILE: <完整路径>]\n"
        "5. 如果找到多个候选，回复 [FILES: 路径1, 路径2, ...]\n"
        "6. 如果完全找不到，回复 [NONE]"
    )


def parse_llm_response(response: str) -> Tuple[Optional[str], List[str]]:
    """Parse the supervisor LLM's response for file paths.

    Returns (single_path, [candidates]).
    - single_path is None if no single match
    - candidates is empty if nothing found
    """
    # Try [FILE: ...]
    file_match = re.search(r'\[FILE:\s*([^\]]+)\]', response, re.IGNORECASE)
    if file_match:
        path = file_match.group(1).strip()
        return path, [path]

    # Try [FILES: ...]
    files_match = re.search(r'\[FILES:\s*([^\]]+)\]', response, re.IGNORECASE)
    if files_match:
        raw = files_match.group(1).strip()
        # Split by comma, newline, or semicolon
        paths = re.split(r'[,\n;]+', raw)
        paths = [p.strip() for p in paths if p.strip()]
        return (paths[0] if len(paths) == 1 else None), paths

    # Try [NONE]
    if re.search(r'\[NONE\]', response, re.IGNORECASE):
        return None, []

    return None, []


def build_fallback_listing(query: str, project_dir: str, max_files: int = 15) -> FileSelectionState:
    """Layer 3 fallback — list files of similar type when nothing else matches.

    Uses keyword expansion to find files with related names.
    """
    candidates = direct_search(query, project_dir, max_results=max_files)
    return FileSelectionState(
        candidates=candidates,
        query=query,
    )
