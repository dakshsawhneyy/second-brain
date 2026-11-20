"""The commitment ledger: parse what he promises, store it as cards, close it out, and compute the facts Vikram may cite.

Deterministic code only. The model never decides statuses, counts or tone states.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from ..schema import Card, MentorMeta, Topic
from ..store import Store

SOURCE = "mentor"
MAX_ITEMS = 3
DAY_CUTOFF_HOURS = 4   # a 00:30 entry still belongs to the previous mentor day
ACTION_VERBS = ("send", "ship", "commit", "publish", "deploy", "apply", "write", "call", "message", "demo", "record",
                "submit", "email", "post", "push", "finish", "fix", "talk", "ask", "reach", "contact", "pitch", "list")
VAGUE_WORDS = ("learn", "explore", "work on", "study", "think about", "look into", "research", "try to", "figure out",
               "get better", "improve", "stuff", "things")
JOB_WORDS = ("apply", "application", "applications", "interview", "resume", "cv", "recruiter", "linkedin", "outreach",
             "job", "cold email", "referral")
PRODUCT_WORDS = ("landing", "customer", "customers", "pricing", "validate", "users", "launch", "waitlist", "demo", "skipats")
_WHEN = re.compile(r"\b(\d{1,2}:\d{2}\s*(?:am|pm)?|\d{1,2}\s*(?:am|pm)|noon|midnight|tonight|this morning|this afternoon|"
                   r"this evening|before\s+\w+|after\s+\w+|by\s+\w+)\b", re.IGNORECASE)
_BULLET = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s*")
_TAG = re.compile(r"#(job|product|other)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Item:
    text: str
    bet: str
    when: str | None
    vague: bool


def mentor_day(now: datetime) -> date:
    return (now - timedelta(hours=DAY_CUTOFF_HOURS)).date()


def _bet(text: str, tag: str | None) -> str:
    if tag:
        return tag.lower()
    low = text.lower()
    if any(w in low for w in JOB_WORDS):
        return "job"
    if any(w in low for w in PRODUCT_WORDS):
        return "product"
    return "other"


def looks_like_commitments(text: str) -> bool:
    """A short list of lines with at least one action verb. Anything else is treated as a normal journal message."""
    lines = [l for l in text.splitlines() if l.strip()]
    if not 1 <= len(lines) <= 6 or any(len(l) > 220 for l in lines):
        return False
    return any(any(re.search(rf"\b{v}\w*", l.lower()) for v in ACTION_VERBS) for l in lines)


def parse_commitments(text: str) -> tuple[list[Item], int]:
    """Return (up to MAX_ITEMS items, number dropped because he gave more than three)."""
    items: list[Item] = []
    for line in text.splitlines():
        line = _BULLET.sub("", line).strip()
        if not line:
            continue
        tag = _TAG.search(line)
        clean = _TAG.sub("", line).strip(" .")
        if not clean:
            continue
        when = _WHEN.search(clean)
        low = clean.lower()
        has_verb = any(re.search(rf"\b{v}\w*", low) for v in ACTION_VERBS)
        vague = (not has_verb) or any(w in low for w in VAGUE_WORDS)
        items.append(Item(text=clean[:200], bet=_bet(clean, tag.group(1) if tag else None),
                          when=when.group(1) if when else None, vague=vague))
    return items[:MAX_ITEMS], max(len(items) - MAX_ITEMS, 0)


def _commitment_cards(store: Store, day: date) -> list[Card]:
    cards = [c for c in store.iter_cards() if c.type == "commitment" and c.mentor and c.mentor.day == day]
    return sorted(cards, key=lambda c: (c.mentor.item or 99, c.id))


def today_items(store: Store, now: datetime) -> list[Card]:
    return _commitment_cards(store, mentor_day(now))


def create_commitments(store: Store, items: list[Item], now: datetime) -> list[Card]:
    day = mentor_day(now)
    existing = _commitment_cards(store, day)
    room = max(MAX_ITEMS - len(existing), 0)
    created: list[Card] = []
    for offset, it in enumerate(items[:room], start=1):
        n = len(existing) + offset
        card = Card(
            id=f"mc_{day:%Y%m%d}_{n}", source=SOURCE, type="commitment", title=it.text[:80], consumed_at=now,
            topic=Topic(primary="uncertain"), visibility="private", channel=None,
            mentor=MentorMeta(day=day, item=n, bet=it.bet, when=it.when, vague=it.vague,
                              late=now.hour >= 18 and now.hour < 24),
        )
        store.write_card(card)
        created.append(card)
    return created


def close_item(store: Store, card_id: str, status: str, *, reason: str | None = None, proof: str | None = None,
               auto: bool = False) -> Card:
    card = store.read_card(card_id)
    meta = card.mentor.model_copy(update={
        "status": status, "reason": reason[:300] if reason else None, "auto_closed": auto,
        "evidence": ("claimed" if (status == "kept") else None),
        "evidence_refs": ([proof[:200]] if proof else []),
    })
    updated = card.model_copy(update={"mentor": meta})
    store.write_card(updated)
    return updated


def set_miss_category(store: Store, card_id: str, category: str) -> None:
    card = store.read_card(card_id)
    store.write_card(card.model_copy(update={"mentor": card.mentor.model_copy(update={"miss_category": category})}))


# --- facts -------------------------------------------------------------------------------------------

def _recent_items(store: Store, now: datetime, days: int) -> list[Card]:
    first = mentor_day(now) - timedelta(days=days)
    return [c for c in store.iter_cards()
            if c.type == "commitment" and c.mentor and c.mentor.day >= first and c.mentor.day <= mentor_day(now)]


def keep_stats(store: Store, now: datetime, days: int = 7) -> tuple[int, int]:
    """(kept, missed) over the last `days` mentor days, today's still-open items excluded."""
    cards = _recent_items(store, now, days)
    return (sum(1 for c in cards if c.mentor.status == "kept"), sum(1 for c in cards if c.mentor.status == "missed"))


def days_since_kept(store: Store, now: datetime, bet: str) -> int | None:
    kept = [c.mentor.day for c in store.iter_cards()
            if c.type == "commitment" and c.mentor and c.mentor.status == "kept" and c.mentor.bet == bet]
    return (mentor_day(now) - max(kept)).days if kept else None


def tone_for(store: Store, now: datetime, phase: int) -> str:
    """glad / disappointed / direct / warm. `hard` is not available before phase 2 (day 11+) and is not built yet."""
    today = mentor_day(now)
    yesterday = today - timedelta(days=1)
    cards = _recent_items(store, now, 3)
    y = [c for c in cards if c.mentor.day == yesterday]
    recent_miss = [c for c in cards if c.mentor.status == "missed" and c.mentor.day < today]
    if len(recent_miss) >= 2 or any(c.mentor.status == "missed" and not c.mentor.reason for c in recent_miss):
        return "direct"
    if recent_miss and any(c.mentor.day == yesterday for c in recent_miss):
        return "disappointed"
    if y and all(c.mentor.status == "kept" for c in y):
        return "glad"
    return "warm"


def build_facts(store: Store, now: datetime) -> list[str]:
    """Lines Vikram may cite. Each starts with a bracketed id; nothing else may be referenced."""
    today = mentor_day(now)
    lines: list[str] = []
    for label, day in (("today", today), ("yesterday", today - timedelta(days=1))):
        for c in _commitment_cards(store, day):
            m = c.mentor
            extra = f" when={m.when}" if m.when else ""
            extra += f" reason=\"{m.reason}\"" if m.reason else ""
            lines.append(f"[{c.id}] commitment {label}: \"{c.title}\" status={m.status} evidence={m.evidence or 'none'} "
                         f"bet={m.bet}{extra}")
    total = sum(1 for c in store.iter_cards() if c.type == "commitment")
    if total == 0:  # do not let the model read "nothing on record" as "he never keeps his word"
        lines.append("[pattern_start] no commitments are on record yet: mentoring has only just started, so there is "
                     "no keep-rate or history to judge")
        return lines
    kept, missed = keep_stats(store, now)
    if kept + missed:
        lines.append(f"[pattern_keep] last 7 days: kept {kept} of {kept + missed} closed commitments")
    lines.append(f"[pattern_total] commitments on record so far: {total}")
    for bet in ("job", "product"):
        d = days_since_kept(store, now, bet)
        lines.append(f"[pattern_{bet}] days since a kept {bet}-bet commitment: "
                     + (f"none kept yet among the {total} on record" if d is None else str(d)))
    return lines
