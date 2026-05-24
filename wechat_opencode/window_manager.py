"""Window manager — fast PowerShell-based window control (no LLM)."""

import glob as glob_mod
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


def _ps(cmd: str, timeout: int = 5) -> Tuple[bool, str]:
    """Run a PowerShell command, return (success, output)."""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd],
            capture_output=True, text=True, timeout=timeout,
        )
        out = result.stdout.strip()
        if result.returncode != 0:
            err = result.stderr.strip()
            if err:
                out = (out + "\n" + err).strip()
            return False, out or f"exit code {result.returncode}"
        return True, out
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception as e:
        return False, str(e)


def get_running_windows() -> List[dict]:
    """Return list of running processes that have a visible window.

    Each entry: {name, title, pid}
    """
    script = """
    Get-Process | Where-Object { $_.MainWindowTitle -ne '' } |
        Select-Object Name, MainWindowTitle, Id |
        Sort-Object Name |
        ForEach-Object {
            "$($_.Name)|$($_.MainWindowTitle)|$($_.Id)"
        }
    """
    ok, out = _ps(script)
    if not ok or not out:
        return []

    windows = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|", 2)
        if len(parts) >= 2:
            windows.append({
                "name": parts[0].strip(),
                "title": parts[1].strip() if len(parts) > 1 else "",
                "pid": parts[2].strip() if len(parts) > 2 else "",
            })
    return windows


def focus_window(query: str) -> Tuple[bool, str]:
    """Find and activate a window matching *query* (fuzzy).

    Returns (success, message). The message describes what happened
    or lists candidates if ambiguous.
    """
    if not query:
        return False, "用法: /focus <应用名>  例如: /focus chrome"

    windows = get_running_windows()
    if not windows:
        return False, "没有找到运行中的窗口"

    query_lower = query.lower()
    candidates = []

    for w in windows:
        name_lower = w["name"].lower()
        title_lower = w["title"].lower()

        # Score: exact name match = highest, substring = medium
        if query_lower == name_lower:
            candidates.append((w, 1.0))
        elif query_lower in name_lower or query_lower in title_lower:
            # Score higher for shorter distance
            score = 0.7
            if query_lower in name_lower:
                score = 0.8
            candidates.append((w, score))

    if not candidates:
        return False, f"未找到匹配 '{query}' 的窗口。用 /apps 查看运行中的应用"

    # Sort by score
    candidates.sort(key=lambda x: x[1], reverse=True)

    if len(candidates) == 1 or candidates[0][1] >= 0.9:
        # Single or high-confidence match → activate
        return _activate_window(candidates[0][0])

    # Multiple candidates → list them
    lines = [f'🔍 "/focus {query}" 匹配到:']
    for i, (w, _) in enumerate(candidates[:8], 1):
        display = w["title"] if w["title"] else w["name"]
        lines.append(f"  {i}. {w['name']} — {display[:60]}")
    lines.append("回复编号选择，或 c 取消")
    return False, "\n".join(lines)


def focus_window_by_index(query: str, index: int) -> Tuple[bool, str]:
    """Focus the Nth candidate from a previous focus_window call."""
    # Re-run the search to get candidates
    windows = get_running_windows()
    query_lower = query.lower()
    candidates = []

    for w in windows:
        name_lower = w["name"].lower()
        title_lower = w["title"].lower()
        if query_lower == name_lower:
            candidates.append(w)
        elif query_lower in name_lower or query_lower in title_lower:
            candidates.append(w)

    candidates.sort(key=lambda w: (
        query_lower == w["name"].lower(),
        query_lower in w["name"].lower(),
    ), reverse=True)

    if index < 0 or index >= len(candidates):
        return False, f"编号超出范围 (1-{len(candidates)})"

    return _activate_window(candidates[index])


def _activate_window(w: dict) -> Tuple[bool, str]:
    """Use PowerShell to activate the window by process name."""
    script = f"""
    Add-Type @"
    using System;
    using System.Runtime.InteropServices;
    public class Win32 {{
        [DllImport("user32.dll")]
        public static extern bool SetForegroundWindow(IntPtr hWnd);
        [DllImport("user32.dll")]
        public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
        [DllImport("user32.dll")]
        public static extern IntPtr FindWindow(string lpClassName, string lpWindowName);
    }}
"@
    $proc = Get-Process -Id {w['pid']} -ErrorAction SilentlyContinue
    if ($proc) {{
        $hwnd = $proc.MainWindowHandle
        if ($hwnd -ne [IntPtr]::Zero) {{
            [Win32]::ShowWindow($hwnd, 9)  # SW_RESTORE
            [Win32]::SetForegroundWindow($hwnd)
            Write-Output "OK"
        }} else {{
            Write-Output "NO_HWND"
        }}
    }} else {{
        Write-Output "NOT_FOUND"
    }}
    """
    ok, out = _ps(script, timeout=8)
    if ok and "OK" in out:
        name = w["title"] or w["name"]
        return True, f"✅ 已切换到: {name}"
    return False, f"❌ 无法切换窗口: {w['name']}"


def show_desktop() -> Tuple[bool, str]:
    """Minimize all windows (show desktop)."""
    script = """
    (New-Object -ComObject Shell.Application).MinimizeAll()
    Write-Output "OK"
    """
    ok, out = _ps(script)
    if ok:
        return True, "✅ 已显示桌面"
    return False, f"❌ 操作失败: {out}"


def minimize_current() -> Tuple[bool, str]:
    """Minimize the currently active window."""
    script = """
    Add-Type @"
    using System;
    using System.Runtime.InteropServices;
    public class Win32 {
        [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
        [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    }
"@
    $hwnd = [Win32]::GetForegroundWindow()
    if ($hwnd -ne [IntPtr]::Zero) {
        [Win32]::ShowWindow($hwnd, 6)  # SW_MINIMIZE
        Write-Output "OK"
    } else {
        Write-Output "NO_WINDOW"
    }
    """
    ok, out = _ps(script)
    if ok:
        return True, "✅ 已最小化当前窗口"
    return False, f"❌ 操作失败: {out}"


def maximize_current() -> Tuple[bool, str]:
    """Maximize the currently active window."""
    script = """
    Add-Type @"
    using System;
    using System.Runtime.InteropServices;
    public class Win32 {
        [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
        [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    }
"@
    $hwnd = [Win32]::GetForegroundWindow()
    if ($hwnd -ne [IntPtr]::Zero) {
        [Win32]::ShowWindow($hwnd, 3)  # SW_MAXIMIZE
        Write-Output "OK"
    } else {
        Write-Output "NO_WINDOW"
    }
    """
    ok, out = _ps(script)
    if ok:
        return True, "✅ 已最大化当前窗口"
    return False, f"❌ 操作失败: {out}"


def list_apps() -> str:
    """Format running windows as a numbered list."""
    windows = get_running_windows()
    if not windows:
        return "没有找到运行中的应用窗口"

    # Deduplicate by name, keep the one with the longest title
    seen: dict = {}
    for w in windows:
        name = w["name"].lower()
        if name not in seen or len(w["title"]) > len(seen[name]["title"]):
            seen[name] = w

    sorted_apps = sorted(seen.values(), key=lambda w: w["name"].lower())

    lines = [f"📋 运行中的应用 ({len(sorted_apps)} 个):"]
    for i, w in enumerate(sorted_apps, 1):
        extra = f" — {w['title'][:50]}" if w["title"] else ""
        lines.append(f"  {i}. {w['name']}{extra}")

    return "\n".join(lines)


# --- File type hints: common extensions for ambiguous Chinese queries ---
_FILE_TYPE_HINTS = {
    "报告": [".docx", ".pdf", ".pptx", ".xlsx"],
    "文档": [".docx", ".pdf", ".txt", ".md"],
    "表格": [".xlsx", ".csv", ".xls"],
    "照片": [".jpg", ".png", ".jpeg", ".heic"],
    "图片": [".jpg", ".png", ".jpeg", ".bmp"],
    "视频": [".mp4", ".mov", ".avi", ".mkv"],
    "音乐": [".mp3", ".wav", ".flac"],
    "代码": [".py", ".js", ".ts", ".java"],
    "压缩": [".zip", ".rar", ".7z"],
    "合同": [".docx", ".pdf"],
    "简历": [".docx", ".pdf"],
    "发票": [".pdf", ".jpg"],
}

# Extensionless files that should be treated as files not apps
_EXTENSIONLESS = {"readme", "makefile", "dockerfile", "license",
                   "changelog", "gemfile", "rakefile", "vagrantfile"}


def _is_file_query(query: str) -> bool:
    """Determine if query likely refers to a file rather than an app."""
    ql = query.lower().strip()
    # Has extension
    if "." in ql and not ql.startswith("."):
        return True
    # Has path separator
    if "/" in ql or "\\" in ql:
        return True
    # Known extensionless file
    if ql in _EXTENSIONLESS:
        return True
    # Contains Chinese (file names often in Chinese, app names rarely)
    if any('\u4e00' <= c <= '\u9fff' for c in ql):
        return True
    return False


def _detect_drives() -> List[str]:
    """Return list of available drive roots (e.g. ['C:\\', 'D:\\'])."""
    drives = []
    for letter in "CDEFGH":
        root = f"{letter}:\\"
        if os.path.exists(root):
            drives.append(root)
    return drives


def _build_file_patterns(query: str) -> List[str]:
    """Build search patterns from query, including type hint expansions."""
    patterns = [query]
    # Chinese type hints: "报告" → append "报告.docx", "报告.pdf", etc.
    for cn, exts in _FILE_TYPE_HINTS.items():
        if cn in query:
            for ext in exts:
                patterns.append(query + ext)
            break
    return patterns


def open_app_or_file(query: str, location: str = "",
                     ) -> Tuple[bool, str, Optional[list]]:
    """Open an application or file by name.

    Two-round file search:
      Round 1: Desktop + Downloads
      Round 2: User-chosen location

    *location* is non-empty for Round 2 searches.

    Returns (success, message, candidates_or_None).
    candidates is either None (done), a list of file candidates,
    or a list of location options (type="location").
    """
    if not query:
        return False, "用法: /open <应用名或文件名>\n例如: /open 微信\n例如: /open 报告", None

    # --- App search path ---
    if not _is_file_query(query):
        return _open_app_search(query)

    home = str(Path.home())

    # --- File search ---
    if location:
        return _open_file_round2(query, location, home)

    return _open_file_round1(query, home)


def _open_file_round1(query: str, home: str
                      ) -> Tuple[bool, str, Optional[list]]:
    """Search Desktop + Downloads — small directories, fast."""
    from wechat_opencode.file_transfer import direct_search

    patterns = _build_file_patterns(query)
    all_candidates = []

    for dir_name in ("Desktop", "Downloads"):
        d = os.path.join(home, dir_name)
        if not os.path.isdir(d):
            continue
        for pat in patterns:
            all_candidates.extend(direct_search(pat, d, max_results=5))
            if len(all_candidates) >= 8:
                break
        if len(all_candidates) >= 8:
            break

    # Deduplicate
    seen = set()
    unique = []
    for c in all_candidates:
        if c.path not in seen and os.path.isfile(c.path):
            seen.add(c.path)
            unique.append(c)

    if not unique and len(patterns) > 1:
        # Retry with just the original query (without type hint suffixes)
        for dir_name in ("Desktop", "Downloads"):
            d = os.path.join(home, dir_name)
            if os.path.isdir(d):
                unique.extend(direct_search(query, d, max_results=5))
        seen2 = set()
        unique = [c for c in unique if not (c.path in seen2 or seen2.add(c.path))]

    if not unique:
        # Nothing found → ask for location
        locs = get_location_options(home)
        if not locs:
            return False, "❌ 未找到文件，且没有可用的搜索位置", None
        lines = [f"❌ 桌面和下载文件夹未找到 \"{query}\"", "",
                 "文件可能在哪个位置？"]
        for i, loc in enumerate(locs, 1):
            lines.append(f"  {i}. {loc['label']}")
        lines.append("回复编号选择，或 c 取消")
        return False, "\n".join(lines), locs

    if len(unique) == 1:
        _os_open(unique[0].path)
        return True, f"✅ 已打开: {unique[0].name}", None

    # Multiple candidates
    cand_list = [{"path": c.path, "name": c.name, "type": "file"}
                 for c in unique[:8]]
    lines = [f'🔍 "/open {query}" 找到 {len(cand_list)} 个文件:']
    for i, c in enumerate(cand_list, 1):
        lines.append(f"  {i}. {c['name']}")
    lines.append("回复编号选择，或 c 取消")
    return False, "\n".join(lines), cand_list


def _open_file_round2(query: str, location: str, home: str
                      ) -> Tuple[bool, str, Optional[list]]:
    """Search a user-chosen location."""
    from wechat_opencode.file_transfer import direct_search

    patterns = _build_file_patterns(query)

    if location == "wechat":
        return _search_wechat_files(query, patterns)

    # Normal directory or drive root
    search_dir = location
    if not os.path.isdir(search_dir):
        # Try to resolve as a common name
        name_map = {
            "documents": os.path.join(home, "Documents"),
            "文档": os.path.join(home, "Documents"),
            "downloads": os.path.join(home, "Downloads"),
            "下载": os.path.join(home, "Downloads"),
            "desktop": os.path.join(home, "Desktop"),
            "桌面": os.path.join(home, "Desktop"),
        }
        search_dir = name_map.get(location.lower(), location)

    if not os.path.isdir(search_dir):
        return False, f"❌ 目录不存在: {location}", None

    # For drive roots, search non-recursively first (fast)
    is_drive_root = len(search_dir) == 3 and search_dir[1:] == ":\\"
    candidates = []

    if is_drive_root:
        # Quick scan: list files in drive root only
        try:
            for entry in os.scandir(search_dir):
                if entry.is_file():
                    for pat in patterns:
                        if pat.lower() in entry.name.lower():
                            stat = entry.stat()
                            from wechat_opencode.types import FileCandidate
                            candidates.append(FileCandidate(
                                path=entry.path, name=entry.name,
                                size=stat.st_size, modified=stat.st_mtime,
                                similarity=0.6,
                            ))
                            break
                    if len(candidates) >= 10:
                        break
        except (PermissionError, OSError):
            pass

        if not candidates:
            # Ask if user wants recursive search
            return False, (
                f"❌ {search_dir} 根目录未找到 \"{query}\"\n"
                "要搜索子目录吗？(回复 y 继续，c 取消)"
            ), [{"type": "confirm_subdirs", "path": search_dir, "label": "搜索子目录"}]

    else:
        # Non-root: use direct_search (already has depth/speed limits)
        for pat in patterns:
            candidates.extend(direct_search(pat, search_dir, max_results=8))
            if len(candidates) >= 8:
                break

    # Deduplicate
    seen = set()
    unique = []
    for c in candidates:
        if c.path not in seen and os.path.isfile(c.path):
            seen.add(c.path)
            unique.append(c)

    if not unique:
        return False, (
            f"❌ {search_dir} 未找到 \"{query}\"\n"
            "要交给 AI 深度搜索吗？(/file 命令可以帮你)"
        ), None

    if len(unique) == 1:
        _os_open(unique[0].path)
        return True, f"✅ 已打开: {unique[0].name}", None

    cand_list = [{"path": c.path, "name": c.name, "type": "file"}
                 for c in unique[:8]]
    lines = [f'🔍 在 {os.path.basename(search_dir)} 找到 {len(cand_list)} 个文件:']
    for i, c in enumerate(cand_list, 1):
        lines.append(f"  {i}. {c['name']}")
    lines.append("回复编号选择，或 c 取消")
    return False, "\n".join(lines), cand_list


def _search_wechat_files(query: str, patterns: List[str]
                         ) -> Tuple[bool, str, Optional[list]]:
    """Search WeChat received files."""
    home = str(Path.home())
    wechat_base = os.path.join(home, "Documents", "WeChat Files")
    if not os.path.isdir(wechat_base):
        return False, "❌ 未找到微信文件目录", None

    candidates = []
    try:
        for wxid_dir in os.scandir(wechat_base):
            if not wxid_dir.is_dir():
                continue
            file_dir = os.path.join(wxid_dir.path, "FileStorage", "File")
            if not os.path.isdir(file_dir):
                continue
            # Search WeChat file directories (by month)
            for month_dir in os.scandir(file_dir):
                if not month_dir.is_dir():
                    continue
                try:
                    for entry in os.scandir(month_dir.path):
                        if entry.is_file():
                            name_lower = entry.name.lower()
                            for pat in patterns:
                                if pat.lower() in name_lower:
                                    stat = entry.stat()
                                    from wechat_opencode.types import FileCandidate
                                    candidates.append(FileCandidate(
                                        path=entry.path, name=entry.name,
                                        size=stat.st_size, modified=stat.st_mtime,
                                        similarity=0.5,
                                    ))
                                    break
                        if len(candidates) >= 15:
                            break
                except (PermissionError, OSError):
                    continue
                if len(candidates) >= 15:
                    break
            if len(candidates) >= 15:
                break
    except (PermissionError, OSError):
        pass

    if not candidates:
        return False, f"❌ 微信文件中未找到 \"{query}\"", None

    if len(candidates) == 1:
        _os_open(candidates[0].path)
        return True, f"✅ 已打开微信文件: {candidates[0].name}", None

    cand_list = [{"path": c.path, "name": c.name, "type": "file"}
                 for c in sorted(candidates, key=lambda x: x.modified, reverse=True)[:8]]
    lines = [f'🔍 微信文件中找到 {len(cand_list)} 个匹配:']
    for i, c in enumerate(cand_list, 1):
        lines.append(f"  {i}. {c['name']}")
    lines.append("回复编号选择，或 c 取消")
    return False, "\n".join(lines), cand_list


def get_location_options(home: str) -> list:
    """Return available search locations for Round 2.

    Each entry: {"type": "location", "path": ..., "label": ...}
    """
    options = []

    # Dynamic drives (skip C: which is the system drive, included separately)
    for drive in _detect_drives():
        label = f"{drive[0]}盘 ({drive})"
        options.append({"type": "location", "path": drive, "label": label})

    # Common directories
    common = [
        ("Documents", "文档文件夹"),
        ("Downloads", "下载文件夹"),
    ]
    for dirname, label in common:
        p = os.path.join(home, dirname)
        if os.path.isdir(p):
            options.append({"type": "location", "path": p, "label": label})

    # WeChat files
    wechat_dir = os.path.join(home, "Documents", "WeChat Files")
    if os.path.isdir(wechat_dir):
        options.append({"type": "location", "path": "wechat", "label": "微信接收文件"})

    return options


def open_by_index(query: str, index: int,
                   candidates: list) -> Tuple[bool, str, Optional[list]]:
    """Open the Nth candidate from a previous search.

    Returns (ok, msg, candidates_or_None) — same format as open_app_or_file.
    """
    if index < 0 or index >= len(candidates):
        return False, f"编号超出范围 (1-{len(candidates)})", None

    c = candidates[index]

    # Handle location options → do Round 2 search
    if c.get("type") == "location":
        home = str(Path.home())
        return _open_file_round2(query, c["path"], home)

    # Handle subdirectory confirmation
    if c.get("type") == "confirm_subdirs":
        from wechat_opencode.file_transfer import direct_search
        search_dir = c["path"]
        found = []
        for pat in _build_file_patterns(query):
            found.extend(direct_search(pat, search_dir, max_results=8))
        if not found:
            return False, f"❌ {search_dir} 子目录也未找到 \"{query}\"", None
        if len(found) == 1:
            _os_open(found[0].path)
            return True, f"✅ 已打开: {found[0].name}", None
        cand_list = [{"path": x.path, "name": x.name, "type": "file"}
                     for x in found[:8]]
        lines = [f'🔍 {search_dir} 子目录找到 {len(cand_list)} 个文件:']
        for i, fc in enumerate(cand_list, 1):
            lines.append(f"  {i}. {fc['name']}")
        lines.append("回复编号选择，或 c 取消")
        return False, "\n".join(lines), cand_list

    # Running app
    if c.get("type") == "running":
        ok, msg = _activate_window_by_name(c["path"])
        return ok, msg, None

    # File
    if c.get("type") == "file":
        _os_open(c["path"])
        return True, f"✅ 已打开: {c['name']}", None

    # App
    ok, msg = _launch_app(c["path"])
    return ok, msg, None


def _open_app_search(query: str) -> Tuple[bool, str, Optional[list]]:
    """Find and launch/switch to an application.

    Priority: running window → Start Menu → PATH → Program Files.
    """
    # 1. Check if already running → switch to it
    windows = get_running_windows()
    query_lower = query.lower()
    running_matches = []
    for w in windows:
        name_lower = w["name"].lower()
        if query_lower in name_lower or query_lower in w["title"].lower():
            running_matches.append(w)

    if len(running_matches) == 1:
        return _activate_window(running_matches[0]) + (None,)

    # 2. Search for installed app
    installed = _search_installed_apps(query)
    if len(installed) == 1:
        ok, msg = _launch_app(installed[0])
        return ok, msg, None

    # 3. Combine running + installed for candidate list
    all_candidates = []
    for w in running_matches[:5]:
        all_candidates.append({
            "path": w["name"],
            "name": f"{w['name']} (运行中)",
            "type": "running",
        })
    for app in installed[:8]:
        all_candidates.append({
            "path": app,
            "name": os.path.basename(app),
            "type": "app",
        })

    if not all_candidates:
        return False, f"❌ 未找到应用: {query}", None

    if len(all_candidates) == 1:
        if all_candidates[0]["type"] == "running":
            return _activate_window_by_name(all_candidates[0]["path"]) + (None,)
        else:
            ok, msg = _launch_app(all_candidates[0]["path"])
            return ok, msg, None

    # Multiple candidates
    lines = [f'🔍 "/open {query}" 匹配到:']
    for i, c in enumerate(all_candidates, 1):
        tag = "▶ 运行中" if c["type"] == "running" else "📦 可启动"
        lines.append(f"  {i}. {c['name']}  {tag}")
    lines.append("回复编号选择，或 c 取消")
    return False, "\n".join(lines), all_candidates


def _search_installed_apps(query: str) -> List[str]:
    """Search for executable matching query in common locations."""
    query_lower = query.lower()
    results = []

    # Search Start Menu shortcuts
    start_menu = os.path.join(os.environ.get("APPDATA", ""),
                              r"Microsoft\Windows\Start Menu\Programs")
    if os.path.isdir(start_menu):
        for root, _, files in os.walk(start_menu):
            for f in files:
                name_lower = f.lower()
                if query_lower in name_lower and name_lower.endswith((".lnk", ".exe")):
                    results.append(os.path.join(root, f))
                    if len(results) >= 10:
                        break
            if len(results) >= 10:
                break

    # Search PATH for executables
    if not results:
        try:
            r = subprocess.run(
                ["where", query + "*"], capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0:
                for line in r.stdout.strip().splitlines():
                    line = line.strip()
                    if line.lower().endswith(".exe"):
                        results.append(line)
                        if len(results) >= 10:
                            break
        except Exception:
            pass

    # Search common install directories
    if not results:
        common_dirs = [
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs"),
        ]
        for base in common_dirs:
            if not os.path.isdir(base):
                continue
            try:
                for entry in os.scandir(base):
                    if query_lower in entry.name.lower():
                        results.append(entry.path)
                        if len(results) >= 5:
                            break
            except PermissionError:
                continue
            if len(results) >= 5:
                break

    return results[:10]


def _launch_app(path: str) -> Tuple[bool, str]:
    """Launch an application by path or name."""
    try:
        if path.endswith(".lnk"):
            os.startfile(path)
        elif os.path.isfile(path):
            os.startfile(path)
        else:
            # Try as process name
            subprocess.Popen([path], shell=True)
        return True, f"✅ 已启动: {os.path.basename(path)}"
    except Exception as e:
        return False, f"❌ 启动失败: {e}"


def _os_open(path: str) -> None:
    """Open a file with the default application."""
    os.startfile(path)


def _activate_window_by_name(name: str) -> Tuple[bool, str]:
    """Activate a window by process name."""
    windows = get_running_windows()
    name_lower = name.lower()
    for w in windows:
        if w["name"].lower() == name_lower or name_lower in w["name"].lower():
            return _activate_window(w)
    return False, f"❌ 未找到运行中的窗口: {name}"


def open_by_index(query: str, index: int,
                   candidates: list) -> Tuple[bool, str]:
    """Open the Nth candidate from a previous search."""
    if index < 0 or index >= len(candidates):
        return False, f"编号超出范围 (1-{len(candidates)})"

    c = candidates[index]
    if c["type"] == "running":
        return _activate_window_by_name(c["path"])
    elif c["type"] == "file":
        _os_open(c["path"])
        return True, f"✅ 已打开: {c['name']}"
    else:
        return _launch_app(c["path"])
