"""Small persistent state of the mentor conversation (raw/mentor_state.json). Atomic writes, tolerant reads."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

MAX_TURNS = 6
MAX_SENT = 14
TURN_CHARS = 500


class MentorState:
    def __init__(self, path: Path):
        self.path = Path(path)

    def load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        try:
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    def update(self, **changes: Any) -> dict[str, Any]:
        data = self.load()
        data.update(changes)
        self.save(data)
        return data

    # --- conversation memory --------------------------------------------------------------------
    def add_turn(self, who: str, text: str) -> None:
        data = self.load()
        turns = list(data.get("turns", []))
        turns.append({"who": who, "text": " ".join(text.split())[:TURN_CHARS]})
        data["turns"] = turns[-MAX_TURNS:]
        if who == "v":
            sent = list(data.get("sent", []))
            sent.append(text)
            data["sent"] = sent[-MAX_SENT:]
        self.save(data)

    def turns(self) -> list[dict[str, str]]:
        return list(self.load().get("turns", []))

    def sent(self) -> list[str]:
        return list(self.load().get("sent", []))
