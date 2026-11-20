"""Checks every outbound Vikram message must pass before it is sent. Pure functions, no I/O."""

from __future__ import annotations

import re

from .persona import (BANNED_PHRASES, GOAL_WORDS_BLOCKED_WHEN_CONCERNED, PERSON_ATTACKS, TARGET_RAISING,
                      UNSAFE_ADVICE)

_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿⬀-⯿]")
_MARKDOWN = re.compile(r"(\*\*|__|`|^\s{0,3}#{1,6}\s|^\s*[-*•]\s|^\s*\d+[.)]\s)", re.MULTILINE)
_IDS = re.compile(r"\[([A-Za-z0-9_-]{2,60})\]")
_NUMS = re.compile(r"\d{2,}")

_ID = r"(?:tg|mo|cc|adv|adq|dg[dwm]|mc|ck)_(?:\d|[0-9a-f]{6})[\w#-]*"
_ID_BRACKET = re.compile(rf"\s*\[{_ID}\]")
_ID_PAREN = re.compile(rf"\s*\((?:from\s+)?{_ID}(?:\s*,\s*{_ID})*\)")
_ID_BARE = re.compile(rf"\s*\b{_ID}\b")

MAX_WORDS = {"daily": 120, "evening": 170, "onboarding": 120, "letter": 350, "chat": 230}


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def _trigrams(text: str) -> set[tuple[str, str, str]]:
    w = _words(text)
    return {tuple(w[i:i + 3]) for i in range(len(w) - 2)}


def check(text: str, *, kind: str, tone: str, allowed_ids: set[str], allowed_text: str, recent: list[str]) -> list[str]:
    """Return the names of the rules the text breaks (empty list = OK)."""
    low = text.lower()
    fails: list[str] = []
    if len(_words(text)) > MAX_WORDS.get(kind, 120):
        fails.append("too_long")
    if "!" in text or _EMOJI.search(text) or _MARKDOWN.search(text):
        fails.append("format")
    if any(p in low for p in BANNED_PHRASES):
        fails.append("banned_phrase")
    if any(p in low for p in UNSAFE_ADVICE):
        fails.append("unsafe_advice")
    if any(p in low for p in PERSON_ATTACKS):
        fails.append("person_attack")
    if any(p in low for p in TARGET_RAISING):
        fails.append("raises_target")
    if tone == "concerned" and any(p in low for p in GOAL_WORDS_BLOCKED_WHEN_CONCERNED):
        fails.append("goals_while_concerned")
    if kind != "chat":  # structured messages must stay inside the facts; free chat may talk about anything he raised
        if any(i not in allowed_ids for i in _IDS.findall(text)):
            fails.append("unknown_id")
        known = set(_NUMS.findall(allowed_text))
        if any(n not in known for n in _NUMS.findall(text)):
            fails.append("invented_number")
    tri = _trigrams(text)
    for old in recent[-14:]:
        old_tri = _trigrams(old)
        if tri and old_tri and len(tri & old_tri) / len(tri | old_tri) > 0.5:
            fails.append("repetition")
            break
    opening = tuple(_words(text)[:4])
    if opening and any(tuple(_words(o)[:4]) == opening for o in recent[-5:]):
        if "repetition" not in fails:
            fails.append("repetition")
    return fails


def strip_note_ids(text: str) -> str:
    """Remove internal note ids (like [mo_32] or (tg_12)) from a reply: he reads plain words, never our bookkeeping."""
    for pattern in (_ID_BRACKET, _ID_PAREN, _ID_BARE):
        text = pattern.sub("", text)
    return text
