"""Intent Router — analyze user text, decompose into steps, match built-in commands.

Architecture:
    User: "在桌面创建一个文件，然后发给我"
      → Layer 1: Extract atomic steps via keyword/phrase splitting
      → Layer 2: For each step, check if it maps to a built-in /command
      → Layer 3: Return IntentResult with matched commands + LLM fallback steps
"""

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class Step:
    """A single decomposed task step."""
    description: str                     # human-readable: "发送文件到飞书"
    raw_text: str                        # original user words for this step
    matched_command: Optional[str] = None  # e.g. "/file" if matched
    matched_args: Optional[str] = None     # e.g. "C:/Users/1/Desktop/report.docx"
    needs_llm: bool = True               # True if no command matched


@dataclass
class IntentResult:
    """Result of intent analysis."""
    type: str  # "command" | "compound" | "chat" | "task"
    # For direct command hits
    command: Optional[str] = None
    command_args: Optional[str] = None
    # For compound tasks
    steps: List[Step] = field(default_factory=list)
    # For LLM fallback
    llm_prompt: Optional[str] = None


# ── Command mapping: natural language patterns → /command ─────────────

# Only /-prefixed command patterns — natural language matching is handled by Layer 3 LLM.
# (keyword_rules, command_name, has_args)
_COMMAND_PATTERNS: List[Tuple[List[str], str, bool]] = [
    (["/screen"], "/screen", False),
    (["/desktop"], "/desktop", False),
    (["/min"], "/min", False),
    (["/max"], "/max", False),
    (["/apps"], "/apps", False),
    (["/focus"], "/focus", True),
    (["/open"], "/open", True),
    (["/file"], "/file", True),
    (["/ppt"], "/ppt", True),
    (["/model"], "/model", True),
    (["/status"], "/status", False),
    (["/cost"], "/cost", False),
    (["/tasks"], "/tasks", False),
    (["/cancel"], "/cancel", False),
    (["/undo"], "/undo", False),
    (["/cleartasks"], "/cleartasks", False),
    (["/help"], "/help", False),
    (["/new"], "/new", False),
    (["/restart"], "/restart", False),
    (["/cron"], "/cron", True),
    (["/plan"], "/plan", True),
    (["/compact"], "/compact", False),
    (["/progress"], "/progress", True),
    (["/sessions"], "/sessions", False),
]


def match_command(text: str) -> Optional[Tuple[str, Optional[str]]]:
    """Try to match natural language text to a built-in command.

    Returns (command, args) or None if no match.

    Args can be extracted from the text (e.g. "切换到 Chrome"
    → ("/focus", "Chrome")).
    """
    text_lower = text.strip().lower()

    # Phase 1: Exact keyword match (fast path)
    for keywords, command, has_args in _COMMAND_PATTERNS:
        for kw in keywords:
            if kw in text_lower:
                if has_args:
                    # Extract args: remove the keyword and surrounding filler words
                    args = _extract_args(text_lower, kw)
                    if args:
                        return (command, args)
                    # Even without args, return the command for interactive handling
                    return (command, None)
                else:
                    return (command, None)

    return None


def _extract_args(text: str, keyword: str) -> Optional[str]:
    """Extract command arguments from text after removing the keyword."""
    # Remove the keyword from text
    cleaned = text.replace(keyword, "").strip()
    # Remove common connecting words
    for filler in ["一下", "一个", "的", "了", "吧", "吗", "到", "成", "换成", "为"]:
        cleaned = cleaned.replace(filler, "")
    cleaned = " ".join(cleaned.split())  # normalize whitespace
    return cleaned if cleaned else None


# ── Step decomposition ─────────────────────────────────────────────────

_STEP_SPLITTERS = re.compile(
    r'(然后|之后|接着|再|最后|同时|并且|而且|第一步|第二步|第三步|首先|其次)',
)


_STEP_CLEANUP = re.compile(r'^[，,、。.？?！!；;：:\s]+')


def decompose(text: str) -> List[str]:
    """Split text into atomic steps based on natural language cues.

    "在桌面创建一个文件然后发给我" → ["在桌面创建一个文件", "发送给我"]
    """
    parts = _STEP_SPLITTERS.split(text)
    steps = []
    current = ""
    for part in parts:
        if _STEP_SPLITTERS.match(part):
            if current.strip():
                steps.append(current.strip())
            current = ""
        else:
            current += part
    if current.strip():
        steps.append(current.strip())

    if len(steps) <= 1:
        return [text]

    # Clean leading punctuation from each step
    cleaned = []
    for s in steps:
        s = _STEP_CLEANUP.sub("", s).strip()
        if s:
            cleaned.append(s)
    return cleaned if cleaned else steps


# ── Send-intent decomposition ──────────────────────────────────────────

# Patterns that indicate "send to me" at the END of a sentence.
# When matched, decompose into [what_to_do, file_send]
_SEND_INTENT_END = re.compile(
    r'^(.*?)(发给我|发我|发送给我|发过来|传给我|传过来|发到飞书|发到手机|推送给我|发一份给我)$'
)


def decompose_with_send_intent(text: str) -> List[str]:
    """Decompose text that ends with a "send to me" phrase.

    "把桌面来宾市简介发给我" → ["把桌面来宾市简介", "发给我"]
    "帮我写个报告发我" → ["帮我写个报告", "发我"]
    "创建文件然后发送到飞书" → ["创建文件", "发送到飞书"]
    """
    text_stripped = text.strip()

    # First try send-intent ending pattern
    match = _SEND_INTENT_END.match(text_stripped)
    if match:
        prefix = match.group(1).strip()
        if prefix:
            return [prefix, "发送文件到飞书"]

    return decompose(text)


# ── Layer 3: Lightweight LLM classification ───────────────────────────

def parse_classification_output(output: str) -> Optional[IntentResult]:
    """Parse LLM classification JSON into IntentResult."""
    import json as _json
    try:
        clean = output.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[1]
            clean = clean.rsplit("\n```", 1)[0]
        data = _json.loads(clean)
    except Exception:
        logger.warning("Failed to parse LLM classification: %s", output[:200])
        return None

    t = data.get("type", "task")
    if t == "command":
        return IntentResult(type="command", command=data.get("command", ""),
                           command_args=data.get("args", ""))
    if t == "compound" and "steps" in data:
        steps = []
        for s in data["steps"]:
            cmd = s.get("cmd", "")
            steps.append(Step(description=s.get("need", s.get("task", "")),
                            raw_text=s.get("need", ""),
                            matched_command=cmd if cmd and cmd.startswith("/") else None,
                            needs_llm=not (cmd and cmd.startswith("/"))))
        return IntentResult(type="compound", steps=steps)
    if t == "chat":
        return IntentResult(type="chat", llm_prompt=data.get("reply", ""))
    return IntentResult(type="task", llm_prompt=data.get("description", output[:80]))


# ── Main routing function ──────────────────────────────────────────────

def analyze(text: str, session=None) -> IntentResult:
    """Main entry point: analyze user text and return routing decision.

    Three-layer strategy:
    1. Layer 1: / prefix → command (0 overhead)
    2. Layer 2: Decompose + /-prefix command match
    3. Layer 3: Lightweight LLM classification (only if session provided)
    """
    text = text.strip()
    if not text:
        return IntentResult(type="chat", llm_prompt="空消息")

    # Already a /command → pass through
    if text.startswith("/"):
        return IntentResult(type="command")

    # --- Layer 2: Decompose (splitters OR send-intent) + keyword match ---
    has_splitter = bool(_STEP_SPLITTERS.search(text))
    has_send_intent = bool(_SEND_INTENT_END.match(text.strip()))
    
    if has_splitter or has_send_intent:
        raw_steps = decompose_with_send_intent(text)
        steps = []
        for raw in raw_steps:
            match = match_command(raw)
            if match:
                cmd, args = match
                steps.append(Step(description=raw, raw_text=raw,
                                 matched_command=cmd, matched_args=args,
                                 needs_llm=False))
            else:
                steps.append(Step(description=raw, raw_text=raw,
                                 needs_llm=True))
        return IntentResult(type="compound", steps=steps)

    # --- Step 2: Single statement — try direct command match ---
    direct_match = match_command(text)
    if direct_match:
        cmd, args = direct_match
        return IntentResult(type="command", command=cmd, command_args=args)

    # --- Layer 3: Lightweight LLM classification ---
    if session is not None:
        try:
            import json as _json
            prompt = (
                "\u4f60\u662f\u610f\u56fe\u5206\u7c7b\u5668\u3002\u5206\u6790\u7528\u6237\u8f93\u5165\uff0c"
                "\u7406\u89e3\u5176\u771f\u5b9e\u610f\u56fe\uff0c\u7136\u540e\u4ece\u53ef\u7528\u6307\u4ee4"
                "\u5217\u8868\u4e2d\u9009\u62e9\u6700\u5339\u914d\u7684\u6307\u4ee4\u3002\n\n"
                f"\u7528\u6237\u8f93\u5165: {text}\n\n"
                "\u53ef\u7528\u6307\u4ee4\u5217\u8868:\n"
                "/screen - \u622a\u53d6\u7535\u8111\u684c\u9762\u622a\u56fe\n"
                "/desktop - \u663e\u793a\u684c\u9762\uff08\u6700\u5c0f\u5316\u6240\u6709\u7a97\u53e3\uff09\n"
                "/min - \u6700\u5c0f\u5316\u5f53\u524d\u7a97\u53e3\n"
                "/max - \u6700\u5927\u5316\u5f53\u524d\u7a97\u53e3\n"
                "/apps - \u5217\u51fa\u6240\u6709\u8fd0\u884c\u4e2d\u7684\u5e94\u7528\n"
                "/focus <\u5e94\u7528\u540d> - \u5207\u6362\u7a97\u53e3\u5230\u6307\u5b9a\u5e94\u7528\n"
                "/open <\u5e94\u7528/\u6587\u4ef6> - \u6253\u5f00\u5e94\u7528\u6216\u6587\u4ef6\n"
                "/file <\u8def\u5f84> - \u641c\u7d22\u5e76\u53d1\u9001\u6587\u4ef6\u5230\u98de\u4e66\n"
                "/ppt <\u4e3b\u9898> - \u751f\u6210PPT\n"
                "/model <\u6a21\u578b\u540d> - \u5207\u6362AI\u6a21\u578b\n"
                "/status - \u67e5\u770b\u7cfb\u7edf\u5f53\u524d\u72b6\u6001\n"
                "/cost - \u67e5\u770b\u8d39\u7528\u7edf\u8ba1\n"
                "/tasks - \u67e5\u770b\u4efb\u52a1\u5217\u8868\n"
                "/task N - \u67e5\u770b\u4efb\u52a1\u8be6\u60c5\n"
                "/cancel - \u53d6\u6d88\u5f53\u524d\u4efb\u52a1\n"
                "/undo - \u64a4\u9500\u4e0a\u6b21\u64cd\u4f5c\n"
                "/cleartasks - \u6e05\u7a7a\u6240\u6709\u4efb\u52a1\n"
                "/help - \u67e5\u770b\u5e2e\u52a9\n"
                "/new - \u5f00\u542f\u65b0\u4f1a\u8bdd\n"
                "/restart - \u91cd\u542f\u670d\u52a1\n"
                "/cron <\u8868\u8fbe\u5f0f> - \u521b\u5efa\u5b9a\u65f6\u4efb\u52a1\n"
                "/plan <\u76ee\u6807> - \u89c4\u5212\u5e76\u6267\u884c\u4efb\u52a1\n"
                "/compact - \u538b\u7f29\u5bf9\u8bdd\u4e0a\u4e0b\u6587\n"
                "/progress <\u95f4\u9694> - \u8bbe\u7f6e\u8fdb\u5ea6\u62a5\u544a\u95f4\u9694\n"
                "/sessions - \u67e5\u770b\u4f1a\u8bdd\u5217\u8868\n\n"
                "\u91cd\u8981\u5224\u65ad\u89c4\u5219:\n"
                "1. \u7528\u6237\u8bf4\u201c\u5220\u9664\u684c\u9762\u7684\u6587\u4ef6\u201d\u3001"
                "\u201c\u5728\u684c\u9762\u521b\u5efa\u6587\u4ef6\u201d\u3001\u201c\u684c\u9762\u4e0a"
                "\u7684xx\u201d\u7b49 \u2192 \u8fd9\u4e9b\u662fTASK\uff08\u9700\u8981AI\u6267\u884c"
                "\u7684\u64cd\u4f5c\uff09\uff0c\u4e0d\u662f/desktop\u6307\u4ee4\u3002/desktop\u4ec5"
                "\u7528\u4e8e\u201c\u663e\u793a\u684c\u9762\u201d/\u201c\u56de\u5230\u684c\u9762\u201d"
                "/\u201c\u6700\u5c0f\u5316\u6240\u6709\u7a97\u53e3\u201d\u7684\u660e\u786e\u610f\u56fe\u3002\n"
                "2. \u7528\u6237\u8bf4\u201c\u628aX\u53d1\u7ed9\u6211\u201d\u3001\u201c\u628aX\u53d1"
                "\u5230\u98de\u4e66\u201d\u3001\u201cX\u7136\u540e\u53d1\u7ed9\u6211\u201d\u7b49"
                " \u2192 \u8fd9\u662fcompound\uff08\u590d\u5408\u4efb\u52a1\uff09\uff1a\u5148\u7531"
                "AI\u627e\u5230/\u521b\u5efa\u6587\u4ef6\uff0c\u7b2c\u4e8c\u6b65\u7528/file\u53d1"
                "\u9001\u5230\u98de\u4e66\u3002\u683c\u5f0f: "
                '{"type":"compound","steps":[{"need":"\u521b\u5efa/\u627e\u5230X","cmd":""},'
                '{"need":"\u53d1\u9001\u6587\u4ef6\u5230\u98de\u4e66","cmd":"/file"}]}\n'
                "3. \u7528\u6237\u8bf4\u201c\u622a\u56fe\u201d/\u201c\u622a\u5c4f\u201d/\u201c"
                "\u622a\u4e2a\u56fe\u201d \u2192 /screen\n"
                "4. \u7528\u6237\u8bf4\u201c\u8d39\u7528\u201d/\u201c\u82b1\u4e86\u591a\u5c11"
                "\u94b1\u201d/\u201c\u7528\u4e86\u591a\u5c11token\u201d \u2192 /cost\n"
                "5. \u7528\u6237\u8bf4\u201c\u4f60\u597d\u201d/\u201c\u8c22\u8c22\u201d/\u201c"
                "\u5728\u5417\u201d\u7b49\u95f2\u804a \u2192 chat\u7c7b\u578b\uff0creply\u7b80"
                "\u77ed\u56de\u590d\n"
                "6. \u7528\u6237\u610f\u56fe\u662f\u8ba9AI\u6267\u884c\u64cd\u4f5c\uff08\u5199"
                "\u4ee3\u7801\u3001\u521b\u5efa\u6587\u4ef6\u3001\u641c\u7d22\u4fe1\u606f\u3001"
                "\u4fee\u6539\u6587\u4ef6\u7b49\uff09\uff0c\u800c\u975e\u9884\u8bbe\u6307\u4ee4"
                " \u2192 task\u7c7b\u578b\n"
                "7. \u7528\u6237\u8bf4\u201c\u73b0\u5728\u662f\u4ec0\u4e48\u60c5\u51b5\uff1f\u201d\u3001\u201c\u5f00\u59cb\u505a\u4e86\u5417\uff1f\u201d\u3001\u201c\u8fdb\u5ea6\u600e\u4e48\u6837\u4e86\uff1f\u201d\u7b49\u8ffd\u95ee\u8fdb\u5ea6\u7684\u8bdd \u2192 chat\u7c7b\u578b\uff0c\u4e0d\u662f/tasks\u4e5f\u4e0d\u662f/status\u3002\n8. "
                "\u8fd4\u56de\u683c\u5f0f(\u4ec5\u8f93\u51faJSON\uff0c\u4e0d\u8981\u5176\u4ed6"
                "\u4efb\u4f55\u5185\u5bb9):\n"
                '{"type":"command","command":"/\u6307\u4ee4","args":"\u53c2\u6570\u6216\u7a7a'
                '\u5b57\u7b26\u4e32"}\n'
                '{"type":"compound","steps":[{"need":"\u6b65\u9aa4\u63cf\u8ff0","cmd":"/\u6307'
                '\u4ee4\u6216\u7a7a\u5b57\u7b26\u4e32"}]}\n'
                '{"type":"chat","reply":"\u7b80\u77ed\u56de\u590d"}\n'
                '{"type":"task","description":"\u4efb\u52a1\u63cf\u8ff0"}\n\n'
                "\u793a\u4f8b(\u8fd9\u4e0d\u662f\u8f93\u51fa\u7684\u4e00\u90e8\u5206\uff0c\u4ec5"
                "\u4f9b\u7406\u89e3):\n"
                '\u8f93\u5165:"\u622a\u56fe" \u2192 {"type":"command","command":"/screen","args":""}\n'
                '\u8f93\u5165:"\u8d39\u7528" \u2192 {"type":"command","command":"/cost","args":""}\n'
                '\u8f93\u5165:"\u4f60\u597d" \u2192 {"type":"chat","reply":"\u4f60\u597d\uff01'
                '\u6709\u4ec0\u4e48\u53ef\u4ee5\u5e2e\u4f60\u7684\uff1f"}\n'
                '\u8f93\u5165:"\u628a\u684c\u9762\u62a5\u544a\u53d1\u7ed9\u6211" \u2192 '
                '{"type":"compound","steps":[{"need":"\u5728\u684c\u9762\u627e\u5230\u62a5\u544a'
                '\u6587\u4ef6","cmd":""},{"need":"\u53d1\u9001\u6587\u4ef6\u5230\u98de\u4e66",'
                '"cmd":"/file"}]}\n'
                '\u8f93\u5165:"\u5220\u9664\u684c\u9762\u7684\u6587\u4ef6" \u2192 '
                '{"type":"task","description":"\u5220\u9664\u684c\u9762\u4e0a\u7684\u6587\u4ef6"}\n'
                '\u8f93\u5165:"\u5728\u684c\u9762\u521b\u5efa\u6587\u4ef6\u7136\u540e\u53d1\u7ed9'
                '\u6211" \u2192 {"type":"compound","steps":[{"need":"\u5728\u684c\u9762\u521b\u5efa'
                '\u6587\u4ef6","cmd":""},{"need":"\u53d1\u9001\u6587\u4ef6\u5230\u98de\u4e66",'
                '"cmd":"/file"}]}\n'
            )
            result = session.execute(prompt, timeout=5)
            if result and result.success and result.output:
                parsed = parse_classification_output(result.output)
                if parsed is not None:
                    return parsed
        except Exception as e:
            logger.debug("Layer 3 LLM classification failed: %s", e)

    # Fallback: needs full LLM
    return IntentResult(
        type="task",
        steps=[Step(description=text, raw_text=text, needs_llm=True)],
        llm_prompt=text,
    )


# ── Artifact extraction from LLM output ────────────────────────────────

# Patterns to detect file paths in Worker output
_PATH_PATTERNS = [
    # Explicit [FILE: path] tag
    re.compile(r'\[FILE:\s*([^\]]+)\]', re.IGNORECASE),
    # Created/saved file patterns
    re.compile(r'(?:已创建|已保存|已写入|Created|Saved|Written)[:：]\s*([A-Za-z]:[^\s,\n]+)', re.IGNORECASE),
    # Windows path in output
    re.compile(r'([A-Za-z]:\\(?:[^\s\n\\:*?"<>|]+\\)*[^\s\n\\:*?"<>|]+\.\w+)'),
    # Markdown code block filename
    re.compile(r'```(?:\w+)?\s*(?:#|//)\s*([A-Za-z]:[^\s\n]+)'),
]


def extract_artifacts(output: str) -> List[str]:
    """Scan Worker LLM output for file paths that were created/modified.

    Returns list of file paths found in the output.
    """
    found = set()
    for pattern in _PATH_PATTERNS:
        for match in pattern.finditer(output):
            path = match.group(1).strip()
            # Skip paths that look like URLs or code
            if path.startswith("http") or "://" in path:
                continue
            if any(path.endswith(ext) for ext in ('.py', '.txt', '.md', '.docx',
                                                   '.pdf', '.xlsx', '.pptx',
                                                   '.json', '.yaml', '.yml',
                                                   '.html', '.css', '.js',
                                                   '.csv', '.zip', '.png', '.jpg')):
                found.add(path)
    return list(found)


def extract_last_task_from_output(output: str) -> Optional[str]:
    """Extract the [TASK: ...] tag from Supervisor output."""
    import re as _re
    m = _re.search(r'\[TASK:\s*(.+?)\]', output, _re.DOTALL)
    if m:
        return m.group(1).strip().rstrip("]").strip()
    return None
