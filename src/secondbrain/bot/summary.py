"""/summary: a plain-language map of the whole system plus live numbers. Counts only, no card content."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path

from ..store import Store

EXPLAINER = """HOW YOUR SECOND BRAIN WORKS

1. It collects
- Claude Code sessions: summarised automatically every 2 hours, on this PC, by the local model (no Claude quota).
- claude.ai chats: drop the data export in raw/claude-chats/, then run: sb chats
- /private <text> is saved but never sent to Claude.
- Anything you type: plain text, a journal entry, what you learned from a book, a link. All saved.
- YouTube history: a one-time Takeout file (not daily).

2. It stores
Each item becomes a private card (a small JSON file in cards/). Nothing leaves your PC except what you send here.

3. It plans your day
- 09:00-14:00: morning brief = what you did yesterday, one action for today, and a short list below it.
- Actions come from: your own todos first, then leftovers from sessions in your two focus projects, then high-scoring videos.
- Tidy the list: /done 2 (the number is the line in the brief). Under the main action use its Done / Later / Skip buttons.
- From 21:30: evening check-in. Just write what you did

4. It checks you
Day 1 was 2026-11-19. On 2026-12-03 we count how many suggested actions you really did. If it is under about a third, we shrink or change the system.

4b. Vikram, your mentor
He starts with a few days of questions to get to know you, then every morning asks for 1-3 commitments (a time and a first action each) and every evening reviews them. He tells you what you need to hear, not what you want to hear. /ask talks to him any time (max 10 a day). Everything said is saved as cards; /private entries never reach him.
/usage shows how many Claude calls each part used.

5. Commands
/brief  today's plan again
/evening  the check-in
/ask  personal advice from Claude
/done N  tidy the brief
/thought  store a thought silently
/todo /private /book  special writes
/summary  this page
/start  the full list of commands, with examples"""


def _last_sync(sync_log: Path | None) -> str:
    if sync_log is None:
        return "unknown"
    try:
        lines = sync_log.read_text(encoding="utf-8").strip().splitlines()
    except OSError:
        return "never ran"
    if not lines:
        return "never ran"
    parts = [p.strip() for p in lines[-1].split(" | ")]
    result = "ok" if parts[-1] == "exit=0" else "FAILED"
    return f"{parts[0]} ({result})"


def _backup_status(sync_log: Path | None) -> str:
    try:
        parts = [p.strip() for p in sync_log.read_text(encoding="utf-8").strip().splitlines()[-1].split(" | ")]
    except (OSError, IndexError, AttributeError):
        return "unknown"
    return next((p[len("backup: "):] for p in parts if p.startswith("backup: ")), "unknown")


def build_summary(store: Store, now: datetime, sync_log: Path | None = None) -> str:
    cards = list(store.iter_cards())
    by_source = Counter(c.source for c in cards)
    open_own = sum(1 for c in cards if c.source == "telegram" and c.action and c.action.status in {"open", "later"})
    done_own = sum(1 for c in cards if c.source == "telegram" and c.action and c.action.status == "done")
    parts = ", ".join(f"{n} {name}" for name, n in by_source.most_common()) or "none yet"
    stats = (
        "\n\nRIGHT NOW\n"
        f"Cards: {len(cards)} ({parts})\n"
        f"Your todos: {open_own} open, {done_own} done\n"
        f"Last session sync: {_last_sync(sync_log)}\n"
        f"Backup: {_backup_status(sync_log)}\n"
        f"Clock: day {max((now.date() - datetime(2026, 11, 19).date()).days + 1, 1)} of 14"
    )
    return EXPLAINER + stats
