"""Usage telemetry: every model call (Claude and local) is logged with the SECTION of the second brain that made it.

Why: so we can see which part of the system burns the Claude 5-hour quota and optimise it. One JSON line per call in
raw/usage.jsonl (gitignored). Only counts, sizes, timings and token numbers are stored, never prompt or answer text.
"""

from __future__ import annotations

import contextvars
import json
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

_section: contextvars.ContextVar[str] = contextvars.ContextVar("sb_section", default="unlabeled")
_lock = threading.Lock()
_log_path: Path | None = None
WINDOW = timedelta(hours=5)  # Claude plan quota window


def configure(path: Path | None) -> None:
    """Set the log file (the bot, sync and CLI call this once at startup). None disables logging."""
    global _log_path
    _log_path = Path(path) if path else None


@contextmanager
def section(name: str):
    """Everything called inside (including threads started with asyncio.to_thread) is attributed to `name`."""
    token = _section.set(name)
    try:
        yield
    finally:
        _section.reset(token)


def current_section() -> str:
    return _section.get()


def log_call(*, provider: str, model: str, ok: bool, started: float, prompt_chars: int = 0, out_chars: int = 0,
             input_tokens: int | None = None, output_tokens: int | None = None, cache_read_tokens: int | None = None,
             cache_write_tokens: int | None = None, cost_usd: float | None = None, kind: str = "llm",
             now: datetime | None = None, error: str | None = None) -> None:
    """Never raises: telemetry must not break the bot."""
    if _log_path is None:
        return
    row = {
        "ts": (now or datetime.now().astimezone()).isoformat(timespec="seconds"),
        "section": current_section(), "provider": provider, "model": model, "kind": kind, "ok": ok,
        "secs": round(time.monotonic() - started, 2), "prompt_chars": prompt_chars, "out_chars": out_chars,
        "in_tokens": input_tokens, "out_tokens": output_tokens, "cache_read": cache_read_tokens,
        "cache_write": cache_write_tokens, "cost_usd": cost_usd, "error": (error or "")[:80] or None,
    }
    try:
        with _lock:
            _log_path.parent.mkdir(parents=True, exist_ok=True)
            with _log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row) + "\n")
    except OSError:
        pass


def read_rows(path: Path) -> list[dict]:
    rows: list[dict] = []
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        pass
    return rows


@dataclass
class Bucket:
    calls: int = 0
    ok: int = 0
    secs: float = 0.0
    in_tokens: int = 0
    out_tokens: int = 0
    cache_read: int = 0
    cache_write: int = 0
    cost: float = 0.0
    prompt_chars: int = 0
    out_chars: int = 0

    def add(self, r: dict) -> None:
        self.calls += 1
        self.ok += 1 if r.get("ok") else 0
        self.secs += r.get("secs") or 0
        self.in_tokens += r.get("in_tokens") or 0
        self.out_tokens += r.get("out_tokens") or 0
        self.cache_read += r.get("cache_read") or 0
        self.cache_write += r.get("cache_write") or 0
        self.cost += r.get("cost_usd") or 0
        self.prompt_chars += r.get("prompt_chars") or 0
        self.out_chars += r.get("out_chars") or 0

    @property
    def all_in(self) -> int:
        return self.in_tokens + self.cache_read + self.cache_write


@dataclass
class Report:
    since: datetime
    claude_by_section: dict[str, Bucket] = field(default_factory=dict)
    local_by_section: dict[str, Bucket] = field(default_factory=dict)
    claude_by_day: dict[str, Bucket] = field(default_factory=dict)
    peak_window_calls: int = 0
    peak_window_tokens: int = 0
    peak_window_start: str | None = None
    claude_total: Bucket = field(default_factory=Bucket)
    local_total: Bucket = field(default_factory=Bucket)


def build_report(rows: list[dict], since: datetime) -> Report:
    rep = Report(since=since)
    claude_rows: list[tuple[datetime, dict]] = []
    for r in rows:
        try:
            ts = datetime.fromisoformat(r["ts"])
        except (KeyError, ValueError):
            continue
        if ts < since:
            continue
        if r.get("provider") == "claude":
            rep.claude_by_section.setdefault(r.get("section", "unlabeled"), Bucket()).add(r)
            rep.claude_by_day.setdefault(ts.date().isoformat(), Bucket()).add(r)
            rep.claude_total.add(r)
            claude_rows.append((ts, r))
        else:
            rep.local_by_section.setdefault(r.get("section", "unlabeled"), Bucket()).add(r)
            rep.local_total.add(r)
    claude_rows.sort(key=lambda x: x[0])
    lo = 0
    tokens = 0
    for hi, (ts, r) in enumerate(claude_rows):
        tokens += (r.get("in_tokens") or 0) + (r.get("cache_read") or 0) + (r.get("cache_write") or 0) + (r.get("out_tokens") or 0)
        while ts - claude_rows[lo][0] > WINDOW:
            r0 = claude_rows[lo][1]
            tokens -= (r0.get("in_tokens") or 0) + (r0.get("cache_read") or 0) + (r0.get("cache_write") or 0) + (r0.get("out_tokens") or 0)
            lo += 1
        calls = hi - lo + 1
        if calls > rep.peak_window_calls or (calls == rep.peak_window_calls and tokens > rep.peak_window_tokens):
            rep.peak_window_calls, rep.peak_window_tokens = calls, tokens
            rep.peak_window_start = claude_rows[lo][0].isoformat(timespec="minutes")
    return rep


def _fmt_bucket(name: str, b: Bucket) -> str:
    avg = b.secs / b.calls if b.calls else 0
    tok = f"{b.all_in + b.out_tokens:,} tok" if (b.all_in or b.out_tokens) else "tokens n/a"
    cost = f"  ${b.cost:.3f}" if b.cost else ""
    return f"  {name:<22} {b.calls:>4} calls  {b.ok}/{b.calls} ok  {avg:>5.1f}s avg  {tok}{cost}"


def format_report(rep: Report, days: int) -> str:
    lines = [f"USAGE, last {days} day(s)", ""]
    lines.append(f"CLAUDE: {rep.claude_total.calls} calls, {rep.claude_total.all_in + rep.claude_total.out_tokens:,} tokens "
                 f"(in {rep.claude_total.all_in:,} / out {rep.claude_total.out_tokens:,}), list-price value ${rep.claude_total.cost:.3f}")
    lines += [_fmt_bucket(k, v) for k, v in sorted(rep.claude_by_section.items(), key=lambda kv: -kv[1].calls)] or ["  (none)"]
    lines += ["", "CLAUDE per day:"]
    lines += [_fmt_bucket(k, v) for k, v in sorted(rep.claude_by_day.items())] or ["  (none)"]
    if rep.peak_window_calls:
        lines += ["", f"Busiest 5-hour window: {rep.peak_window_calls} calls, {rep.peak_window_tokens:,} tokens, "
                      f"starting {rep.peak_window_start}"]
    lines += ["", f"LOCAL (free, your PC): {rep.local_total.calls} calls, {rep.local_total.secs:.0f}s total"]
    lines += [_fmt_bucket(k, v) for k, v in sorted(rep.local_by_section.items(), key=lambda kv: -kv[1].calls)] or ["  (none)"]
    lines += ["", "Cost shown is the list-price value of tokens, not what your plan charges. Compare sections to see "
                  "what to optimise first."]
    return "\n".join(lines)


def report_text(path: Path, days: int, now: datetime | None = None) -> str:
    now = now or datetime.now().astimezone()
    return format_report(build_report(read_rows(path), now - timedelta(days=days)), days)
