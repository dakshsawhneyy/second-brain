"""Card and tombstone storage: JSON files, atomic writes, safe to re-run."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

from pydantic import ValidationError

from .schema import ID_RE, Card, Tombstone


class Store:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.cards_dir = self.root / "cards"
        self.archive_dir = self.root / "archive"
        self.tombstone_path = self.archive_dir / "tombstones.jsonl"
        self.corrupt_files: list[Path] = []
        self._tomb_ids: set[str] | None = None

    # --- cards -------------------------------------------------------------
    def _card_path(self, card: Card) -> Path:
        when = card.consumed_at
        return self.cards_dir / f"{when.year:04d}" / f"{when.month:02d}" / f"{card.id}.json"

    def _find_card_path(self, id: str) -> Path | None:
        if not ID_RE.match(id):
            return None
        for p in self.cards_dir.glob(f"*/*/{id}.json"):
            return p
        return None

    def write_card(self, card: Card) -> Path:
        path = self._card_path(card)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        try:
            tmp.write_text(card.model_dump_json(indent=2), encoding="utf-8")
            os.replace(tmp, path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        return path

    def read_card(self, id: str) -> Card:
        path = self._find_card_path(id)
        if path is None:
            raise KeyError(id)
        return Card.model_validate_json(path.read_text(encoding="utf-8"))

    def delete_card(self, id: str) -> bool:
        """Remove a card's file. Used only for derived cards (digests) whose source notes are gone or private."""
        if not ID_RE.match(id):
            return False
        removed = False
        for path in self.cards_dir.glob(f"*/*/{id}.json"):
            path.unlink(missing_ok=True)
            removed = True
        return removed

    def iter_card_files(self) -> Iterator[Path]:
        """Every card file, without parsing it (the index decides which ones changed)."""
        yield from sorted(self.cards_dir.glob("*/*/*.json"))

    def read_card_file(self, path: Path) -> Card:
        return Card.model_validate_json(Path(path).read_text(encoding="utf-8"))

    def iter_cards(self) -> Iterator[Card]:
        self.corrupt_files = []
        for path in sorted(self.cards_dir.glob("*/*/*.json")):
            try:
                yield Card.model_validate_json(path.read_text(encoding="utf-8"))
            except (ValueError, ValidationError, OSError):
                self.corrupt_files.append(path)

    # --- tombstones --------------------------------------------------------
    def _load_tombstone_ids(self) -> set[str]:
        if self._tomb_ids is None:
            ids: set[str] = set()
            if self.tombstone_path.is_file():
                for line in self.tombstone_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ids.add(json.loads(line)["id"])
                    except (ValueError, KeyError):
                        continue
            self._tomb_ids = ids
        return self._tomb_ids

    def write_tombstone(self, t: Tombstone) -> None:
        ids = self._load_tombstone_ids()
        if t.id in ids:
            return
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        with self.tombstone_path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(t.model_dump_json() + "\n")
        ids.add(t.id)

    def has(self, id: str) -> bool:
        if not ID_RE.match(id):
            return False
        return self._find_card_path(id) is not None or id in self._load_tombstone_ids()
