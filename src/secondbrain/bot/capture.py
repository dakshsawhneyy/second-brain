"""Turn a Telegram message into a memory card. Pure function: no I/O."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime

from ..schema import Action, Card, KeyPoint, Topic

_PREFIX = re.compile(r"^\s*(book|idea|friction|experiment|decided|done|made|todo|journal|private|thought)\s*:\s*(.*)$", re.IGNORECASE | re.DOTALL)
_URL_ONLY = re.compile(r"^https?://\S+$")
_PREFIX_TYPES = {
    "book": "book",
    "idea": "thought",
    "friction": "friction",
    "experiment": "experiment",
    "decided": "decided",
    "done": "acted",
    "made": "produced",
    "todo": "thought",
    "journal": "thought",
    "thought": "thought",
    "private": "thought",
}
TITLE_MAX = 80


def _title(text: str) -> str:
    return " ".join(text.split())[:TITLE_MAX]


def _point(text: str) -> KeyPoint:
    return KeyPoint(text=text, topic="uncertain", t=None, confidence=1.0)


def parse_capture(text: str, now: datetime, message_id: int | None = None, reply_to: str | None = None) -> Card:
    """Prefixes: book|idea|friction|experiment|decided|done|made. A lone URL is a link; anything else a thought.

    `book:` accepts `title | idea | action`. Captures are always private, topic 'uncertain' until classified.
    With a Telegram message_id the card id is `tg_<message_id>`, so a re-delivered message overwrites its
    own card instead of creating a duplicate. `now` should then be the message's own send time.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    raw = text.strip()
    if not raw:
        raise ValueError("empty capture")

    card_id = (f"tg_{message_id}" if message_id is not None
               else f"tg_{int(now.timestamp())}_{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:4]}")
    base = dict(
        id=card_id,
        source="telegram",
        consumed_at=now,
        topic=Topic(primary="uncertain", secondary=[]),
        visibility="private",
        reply_to=(" ".join(reply_to.split())[:400] or None) if reply_to else None,
    )

    match = _PREFIX.match(raw)
    if match:
        kind, body = match.group(1).lower(), match.group(2).strip()
        if not body:
            raise ValueError(f"empty capture after '{kind}:'")
        card_type = _PREFIX_TYPES[kind]
        if kind == "book":
            if "|" not in body:  # free-text log: what I read / learned / understood / ideas. Keep every paragraph.
                paragraphs = [" ".join(p.split()) for p in re.split(r"\n\s*\n", body) if p.strip()]
                first = paragraphs[0]
                if len(paragraphs) == 1 and len(first) <= TITLE_MAX:  # just a book title
                    return Card(**base, type=card_type, title=first, key_points=[])
                return Card(**base, type=card_type, title=_title(first), key_points=[_point(p) for p in paragraphs])
            parts = [p.strip() for p in body.split("|")]
            if not parts[0]:
                raise ValueError("book capture needs a title")
            idea = parts[1] if len(parts) > 1 else ""
            action = " | ".join(p for p in parts[2:] if p) if len(parts) > 2 else ""
            return Card(**base, type=card_type, title=_title(parts[0]),
                        key_points=[_point(idea)] if idea else [],
                        action=Action(text=action) if action else None)
        if kind == "private":  # stored, but never put in any context pack sent to a non-local model
            return Card(**base, type=card_type, title=_title(body), key_points=[_point(body)], channel="local-only")
        if kind == "todo":  # a task for the morning brief
            return Card(**base, type=card_type, title=_title(body), key_points=[_point(body)], action=Action(text=body))
        return Card(**base, type=card_type, title=_title(body), key_points=[_point(body)])

    if _URL_ONLY.match(raw):
        return Card(**base, type="link", title=raw[:TITLE_MAX * 3], url=raw)
    return Card(**base, type="thought", title=_title(raw), key_points=[_point(raw)])
