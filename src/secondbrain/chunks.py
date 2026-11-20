"""Split a card into paragraph-sized search units, so a long journal is searchable by every paragraph, not just the first."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .schema import Card

CHUNK_MAX_CHARS = 900
MAX_CHUNKS_PER_CARD = 60  # bounds work for absurdly long notes (a 50k-char note is about 56 chunks)
_SENTENCE_END = re.compile(r"(?<=[.!?।])\s+")


@dataclass(frozen=True)
class Chunk:
    id: str
    card_id: str
    ord: int
    text: str  # what is shown and keyword-searched
    context: str = ""  # used only when embedding (meaning), never shown: e.g. the question an answer belongs to


def _hard_split(text: str, limit: int) -> list[str]:
    """Split a sentence longer than `limit`: prefer a space near the end of the window, else cut hard."""
    pieces: list[str] = []
    while len(text) > limit:
        cut = text.rfind(" ", limit // 2, limit)
        cut = limit if cut == -1 else cut + 1
        pieces.append(text[:cut])
        text = text[cut:]
    if text:
        pieces.append(text)
    return pieces


def _split_unit(text: str, limit: int = CHUNK_MAX_CHARS) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for sentence in _SENTENCE_END.split(text):
        for part in (_hard_split(sentence, limit) if len(sentence) > limit else [sentence]):
            if current and len(current) + 1 + len(part) > limit:
                chunks.append(current)
                current = part
            else:
                current = f"{current} {part}" if current else part
    if current:
        chunks.append(current)
    return chunks


def _units(card: Card) -> list[tuple[str, str]]:
    """(text, context) pairs. A "Q: ... / A: ..." pair (mentor interview answers) becomes the answer with the question as
    context, so a reply that echoes the question's words finds the answer and never shows the bot's own question."""
    points = [k.text.strip() for k in card.key_points if k.text.strip()]
    units: list[tuple[str, str]] = []
    if len(points) >= 2 and points[0].startswith("Q: ") and points[1].startswith("A: "):
        units.append((points[1][3:].strip(), points[0][3:].strip()))
        points = points[2:]
    units.extend((p, "") for p in points)
    if card.action and card.action.text.strip() and card.action.text.strip() not in {t for t, _ in units}:
        units.append((card.action.text.strip(), ""))
    if units and card.reply_to:
        text, context = units[0]
        units[0] = (f"(in reply to: {card.reply_to}) {text}", context)
    if not units and card.title.strip():
        units = [(card.title.strip(), "")]
    return [(t, c) for t, c in units if t]


def chunk_card(card: Card) -> list[Chunk]:
    """One chunk per key point and per distinct action; long ones split at sentence ends; a note with no body at all
    is represented by its title; a card with no text anywhere has no chunks."""
    pieces: list[tuple[str, str]] = []
    for text, context in _units(card):
        pieces.extend((part, context) for part in _split_unit(text))
        if len(pieces) >= MAX_CHUNKS_PER_CARD:
            break
    return [Chunk(id=f"{card.id}#{i}", card_id=card.id, ord=i, text=text, context=context)
            for i, (text, context) in enumerate(pieces[:MAX_CHUNKS_PER_CARD])]
