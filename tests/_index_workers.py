"""Worker functions for the two-process index test (kept in a module so multiprocessing can import them on Windows)."""

from datetime import datetime, timezone
from pathlib import Path

from secondbrain.embed import HashEmbedder
from secondbrain.index import Index
from secondbrain.schema import Card, KeyPoint, Topic
from secondbrain.store import Store

WHEN = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)


def make(i: int) -> Card:
    text = f"concurrent note number {i} about kubernetes terraform and habits"
    return Card(id=f"tg_{i}", source="telegram", type="thought", title=text[:50], consumed_at=WHEN,
                topic=Topic(primary="uncertain"), key_points=[KeyPoint(text=text, topic="uncertain", confidence=1.0)])


def bot_like(root: str, db: str, count: int) -> None:
    """What the bot does: save a note to disk, then index it right away."""
    store, index = Store(Path(root)), Index(Path(db), HashEmbedder())
    for i in range(count):
        card = make(i)
        store.write_card(card)
        index.add_card(card)


def sync_like(root: str, db: str, rounds: int) -> None:
    """What the scheduled sync does: update repeatedly, and one forced rebuild in the middle."""
    store, index = Store(Path(root)), Index(Path(db), HashEmbedder())
    for r in range(rounds):
        index.update(store)
        if r == rounds // 2:
            index.rebuild(store)
