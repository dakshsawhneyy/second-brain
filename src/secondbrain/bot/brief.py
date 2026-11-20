"""Morning brief, evening check-in and button feedback. Pure functions over the card store.

Telegram bots are not end-to-end encrypted, so briefs only show video titles, one action and
a focus line the user wrote on purpose. Key-point text and goals never appear.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..schema import ID_RE
from ..store import Store

FALLBACK_ACTION = "Ship one small thing today: a commit, a note, or a message to a person."
DEFAULT_FOCUS = "Two bets: a remote infra role abroad, and a product of your own."
MAX_YESTERDAY = 3
ACTION_WINDOW_DAYS = 7
TITLE_MAX = 80
ACTION_MAX = 300
FOCUS_MAX = 140
CALLBACK_MAX_BYTES = 64
ELIGIBLE_STATUSES = {"open", "later"}


@dataclass(frozen=True)
class Brief:
    text: str
    action_id: str | None = None
    ids: list[str] = field(default_factory=list)  # suggestion card ids in display order (1 = today's action)
    buttons: list[tuple[str, str]] = field(default_factory=list)


def _flat(text: str, limit: int) -> str:
    return " ".join(text.split())[:limit]


def _focus_line(goals_text: str) -> str:
    for line in goals_text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("focus:"):
            value = _flat(stripped[len("focus:"):], FOCUS_MAX)
            if value:
                return value
    return DEFAULT_FOCUS


def _score(card) -> int:
    return card.relevance.score if card.relevance else 0


UNSCORED_SOURCES = {"claude-code", "claude-chat"}
DEFAULT_FOCUS_PROJECTS = ("z second brain", "startup_finder")  # his two bets: this brain and SkipATS
OWN_ITEM_WINDOW_DAYS = 60
SESSION_WINDOW_DAYS = 14
MAX_SUGGESTIONS = 3
MAX_DONE = 3


def _norm(name: str | None) -> str:
    return "".join(ch for ch in (name or "").lower() if ch.isalnum())


def _priority(card, focus: set[str]) -> int | None:
    """3 = his own open item, 2 = a scored card, 1 = a leftover from a session in a focus project, None = not eligible."""
    if card.source == "telegram":
        return 3
    if card.source in UNSCORED_SOURCES:
        return 1 if _norm(card.channel) in focus else None
    return 2 if _score(card) >= 40 else None


def _window(card, now: datetime) -> timedelta:
    if card.source == "telegram":
        return timedelta(days=OWN_ITEM_WINDOW_DAYS)
    if card.source in UNSCORED_SOURCES:
        return timedelta(days=SESSION_WINDOW_DAYS)
    return timedelta(days=ACTION_WINDOW_DAYS)


_STOP = {"the", "and", "for", "with", "that", "this", "from", "into", "your", "you", "are", "was", "has", "have",
         "not", "but", "all", "any", "can", "its", "out", "new", "add", "use"}
RESOLVED_OVERLAP = 0.6


def _stems(text: str) -> set[str]:
    return {w[:6] for w in re.findall(r"[a-z0-9]{3,}", text.lower()) if w not in _STOP}


def _resolved(card, cards) -> bool:
    """True when a LATER card says the same thing was done (session 'did'/'decided' points, or his own /done)."""
    need = _stems(card.action.text)
    if len(need) < 2:
        return False
    for other in cards:
        if other.id == card.id or other.consumed_at <= card.consumed_at:
            continue
        if other.source == "telegram":
            if other.type not in {"acted", "produced"}:
                continue
            texts = [other.title] + [k.text for k in other.key_points]
        elif other.source in UNSCORED_SOURCES:
            if card.source in UNSCORED_SOURCES and other.channel != card.channel:
                continue
            texts = [k.text for k in other.key_points if not k.text.startswith("Open:")]
        else:
            continue
        if any(len(need & _stems(t)) / len(need) >= RESOLVED_OVERLAP for t in texts):
            return True
    return False


def _age_note(card, now: datetime) -> str:
    days = (now - card.consumed_at).days
    return f" (open {days} days)" if days >= 3 else ""


def build_morning_brief(store: Store, goals_text: str, now: datetime,
                        focus_projects: tuple[str, ...] | None = None) -> Brief:
    focus = {_norm(p) for p in (focus_projects if focus_projects is not None else DEFAULT_FOCUS_PROJECTS)}
    cards = [c for c in store.iter_cards() if c.tier != "cold" and c.topic.primary != "noise/entertainment"]
    yesterday = (now - timedelta(days=1)).date()

    def day(c):
        return c.consumed_at.astimezone(now.tzinfo).date()

    seen = sorted((c for c in cards if c.type == "consumed" and day(c) == yesterday),
                  key=lambda c: (-_score(c), c.id))[:MAX_YESTERDAY]
    shipped_types = {"acted", "produced"}  # a decision is not a shipped thing
    own_done = [c for c in cards if c.source == "telegram" and c.type in shipped_types and day(c) == yesterday][:MAX_DONE]
    worked_on = [c for c in cards if c.source in UNSCORED_SOURCES and _norm(c.channel) in focus
                 and day(c) == yesterday][:MAX_DONE]

    ranked = []
    for c in cards:
        if not (c.action and c.action.status in ELIGIBLE_STATUSES):
            continue
        pr = _priority(c, focus)
        if pr is None or now - c.consumed_at > _window(c, now):
            continue
        ranked.append((pr, _score(c), c.consumed_at, c))
    ranked.sort(key=lambda r: (r[0], r[1], r[2]), reverse=True)
    picks, seen_text = [], set()
    for r in ranked:
        key = _norm(r[3].action.text)
        if key in seen_text or _resolved(r[3], cards):
            continue  # the same leftover from another session, or something a later card says is done
        seen_text.add(key)
        picks.append(r[3])
        if len(picks) >= MAX_SUGGESTIONS:
            break
    chosen = picks[0] if picks else None

    lines = ["Good morning.", f"Focus: {_focus_line(goals_text)}", ""]
    if own_done or worked_on or seen:
        lines.append("Yesterday:")
        lines += [f"- Done: {_flat(c.title, TITLE_MAX)}" for c in own_done]
        lines += [f"- Worked on: {_flat(c.title, TITLE_MAX)}" for c in worked_on]
        lines += [f"- Watched: {_flat(c.title, TITLE_MAX)}" for c in seen]
    else:
        lines.append("Yesterday: nothing new was captured.")
    lines += ["", "Today's one action:",
              (_flat(chosen.action.text, ACTION_MAX) + _age_note(chosen, now)) if chosen else FALLBACK_ACTION]
    if len(picks) > 1:
        lines += ["", "Also on your list:"]
        lines += [f"{i}. {_flat(c.action.text, ACTION_MAX)}{_age_note(c, now)}" for i, c in enumerate(picks[1:], start=2)]
        lines += ["Drop one with /skip 2, finish with /done 2."]
    if not (own_done or worked_on):
        lines += ["", "Nothing shipped was logged yesterday. Do the smallest item first, then log it: /done <what you shipped>"]

    buttons: list[tuple[str, str]] = []
    if chosen:
        candidates_buttons = [("Done", f"done:{chosen.id}"), ("Later", f"later:{chosen.id}"), ("Skip", f"skip:{chosen.id}")]
        if all(len(data.encode("utf-8")) <= CALLBACK_MAX_BYTES for _, data in candidates_buttons):
            buttons = candidates_buttons
    return Brief(text="\n".join(lines), action_id=chosen.id if chosen else None,
                 ids=[c.id for c in picks], buttons=buttons)


def build_evening_checkin(now: datetime) -> Brief:
    text = (
        "Evening check-in.\n"
        "What did you produce today? What did you read?\n"
        "Just reply in your own words: what you shipped, what you learned from your book, what got in the way.\n"
        "Use /done <thing> for anything you finished."
    )
    return Brief(text=text)


def apply_feedback(store: Store, callback_data: str) -> None:
    """Handle `done:<id>`, `later:<id>`, `skip:<id>`. Anything unknown or malformed is ignored."""
    verb, _, card_id = callback_data.partition(":")
    if verb not in {"done", "later", "skip"} or not ID_RE.match(card_id):
        return
    try:
        card = store.read_card(card_id)
    except KeyError:
        return
    if card.action is None:
        return
    status = {"done": "done", "later": "later", "skip": "skipped"}[verb]
    acted = {"done": True, "later": card.user.acted, "skip": False}[verb]
    updated = card.model_copy(update={
        "action": card.action.model_copy(update={"status": status}),
        "user": card.user.model_copy(update={"acted": acted}),
    })
    store.write_card(updated)
