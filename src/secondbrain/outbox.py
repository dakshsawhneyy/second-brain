"""Durable outbox: replies the bot generated but could not deliver (network down, Telegram timeout).

A mentor reply or an /ask answer costs a Claude call and changes the mentor's state, so losing it on a failed send
is not acceptable: it is kept here and re-sent, in order, until Telegram accepts it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


class Outbox:
    def __init__(self, path: Path):
        self.path = Path(path)

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"next": 1, "items": {}}
        if not isinstance(data, dict) or not isinstance(data.get("items"), dict):
            return {"next": 1, "items": {}}
        data.setdefault("next", 1)
        return data

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        try:
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    def add(self, text: str) -> int:
        data = self._load()
        oid = int(data["next"])
        data["items"][str(oid)] = text
        data["next"] = oid + 1
        self._save(data)
        return oid

    def done(self, oid: int) -> None:
        data = self._load()
        if data["items"].pop(str(oid), None) is not None:
            self._save(data)

    def pending(self) -> list[tuple[int, str]]:
        return sorted((int(k), v) for k, v in self._load()["items"].items())
