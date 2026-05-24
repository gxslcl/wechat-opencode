"""Cost tracker — accumulate token usage and estimated costs."""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class CostRecord:
    """A single cost measurement."""
    timestamp: float = 0.0
    session_id: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cache_read: int = 0
    cache_write: int = 0
    cost_usd: float = 0.0


@dataclass
class CostSummary:
    """Accumulated cost totals."""
    total_input: int = 0
    total_output: int = 0
    total_reasoning: int = 0
    total_cost: float = 0.0
    total_commands: int = 0
    records: List[CostRecord] = field(default_factory=list)


# Approximate costs per 1M tokens (USD) — conservative estimates
MODEL_COSTS: Dict[str, Dict[str, float]] = {
    "deepseek-chat": {"input": 0.27, "output": 1.10},
    "deepseek-v4-flash": {"input": 0.27, "output": 1.10},
    "deepseek-v4-pro": {"input": 0.55, "output": 2.19},
    "default": {"input": 2.0, "output": 8.0},
}


class CostTracker:
    """Tracks token usage and estimated costs, persisted in JSON."""

    def __init__(self, data_dir: str = "./data") -> None:
        self._data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self._file = os.path.join(data_dir, "costs.json")
        self._summary = self._load()

    def record(
        self,
        session_id: str = "",
        input_tokens: int = 0,
        output_tokens: int = 0,
        reasoning_tokens: int = 0,
        cache_read: int = 0,
        cache_write: int = 0,
        model: str = "",
    ) -> CostRecord:
        """Add a new cost record."""
        cost = self._estimate_cost(
            input_tokens, output_tokens, reasoning_tokens, model,
        )
        record = CostRecord(
            timestamp=time.time(),
            session_id=session_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            reasoning_tokens=reasoning_tokens,
            cache_read=cache_read,
            cache_write=cache_write,
            cost_usd=cost,
        )

        self._summary.total_input += input_tokens
        self._summary.total_output += output_tokens
        self._summary.total_reasoning += reasoning_tokens
        self._summary.total_cost += cost
        self._summary.total_commands += 1
        self._summary.records.append(record)

        # Keep only last 100 records
        if len(self._summary.records) > 100:
            self._summary.records = self._summary.records[-100:]

        self._save()
        return record

    @property
    def summary(self) -> CostSummary:
        return self._summary

    def get_session_cost(self, session_id: str) -> float:
        """Return total cost for a specific session."""
        return sum(
            r.cost_usd for r in self._summary.records
            if r.session_id == session_id
        )

    def format_summary(self) -> str:
        """Return a human-readable cost summary string."""
        s = self._summary
        return (
            f"💰 费用统计\n"
            f"  命令次数: {s.total_commands}\n"
            f"  Token 输入: {self._fmt(s.total_input)}\n"
            f"  Token 输出: {self._fmt(s.total_output)}\n"
            f"  估算费用: ${s.total_cost:.4f}"
        )

    # --- Internal -----------------------------------------------------------

    def _estimate_cost(
        self, input_tokens: int, output_tokens: int,
        reasoning_tokens: int, model: str,
    ) -> float:
        """Estimate cost in USD based on model pricing."""
        rates = MODEL_COSTS.get(model, MODEL_COSTS["default"])
        cost = (input_tokens / 1_000_000) * rates["input"]
        cost += (output_tokens / 1_000_000) * rates["output"]
        if reasoning_tokens:
            cost += (reasoning_tokens / 1_000_000) * rates["input"] * 0.5
        return cost

    def _load(self) -> CostSummary:
        try:
            with open(self._file, "r", encoding="utf-8") as f:
                raw = json.load(f)
            records = [CostRecord(**r) for r in raw.get("records", [])]
            s = raw.get("summary", {})
            return CostSummary(
                total_input=s.get("total_input", 0),
                total_output=s.get("total_output", 0),
                total_reasoning=s.get("total_reasoning", 0),
                total_cost=s.get("total_cost", 0.0),
                total_commands=s.get("total_commands", 0),
                records=records,
            )
        except (FileNotFoundError, json.JSONDecodeError):
            return CostSummary()

    def _save(self) -> None:
        with open(self._file, "w", encoding="utf-8") as f:
            json.dump({
                "summary": {
                    "total_input": self._summary.total_input,
                    "total_output": self._summary.total_output,
                    "total_reasoning": self._summary.total_reasoning,
                    "total_cost": self._summary.total_cost,
                    "total_commands": self._summary.total_commands,
                },
                "records": [
                    {
                        "timestamp": r.timestamp,
                        "session_id": r.session_id,
                        "input_tokens": r.input_tokens,
                        "output_tokens": r.output_tokens,
                        "reasoning_tokens": r.reasoning_tokens,
                        "cache_read": r.cache_read,
                        "cache_write": r.cache_write,
                        "cost_usd": r.cost_usd,
                    }
                    for r in self._summary.records
                ],
            }, f, ensure_ascii=False, indent=2)

    @staticmethod
    def _fmt(n: int) -> str:
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n / 1_000:.1f}K"
        return str(n)
