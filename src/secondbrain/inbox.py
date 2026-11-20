"""Durable inbox: every message he sends is written to disk the moment it arrives, and removed only once it is saved.

Telegram counts a message as delivered as soon as the bot fetches it, so a crash, a dead network or a failed
transcription would otherwise lose it. Whatever is still in the inbox is retried automatically.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

MAX_TRIES = 30  # replay attempts before we stop and tell him


class Inbox:
    def __init__(self, path: Path):
        self.path = Path(path)

    def _load(self) -> dict[str, dict[str, Any]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self, data: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        try:
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    def add(self, mid: int, entry: dict[str, Any]) -> None:
        data = self._load()
        if str(mid) not in data:  # a re-delivered message keeps its original record and try count
            data[str(mid)] = {**entry, "at": time.time(), "tries": 0}
            self._save(data)

    def done(self, mid: int | None) -> None:
        if mid is None:
            return
        data = self._load()
        if data.pop(str(mid), None) is not None:
            self._save(data)

    def bump(self, mid: int) -> int:
        data = self._load()
        entry = data.get(str(mid))
        if entry is None:
            return 0
        entry["tries"] = int(entry.get("tries", 0)) + 1
        self._save(data)
        return entry["tries"]

    def mark_gave_up(self, mid: int) -> None:
        data = self._load()
        if str(mid) in data:
            data[str(mid)]["gave_up"] = True
            self._save(data)

    def pending(self) -> list[tuple[int, dict[str, Any]]]:
        out = []
        for key, entry in self._load().items():
            try:
                out.append((int(key), entry))
            except ValueError:
                continue
        return sorted(out)
