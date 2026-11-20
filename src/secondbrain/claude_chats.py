"""Import claude.ai conversations from an official data export (zip or conversations.json) into private cards.

There is no free live feed for claude.ai chats, so Daksh drops the export into raw/claude-chats/ every few weeks.
Everything is summarised by a LOCAL model (no Claude quota, private text never leaves the laptop), secrets are
redacted first, and a conversation is re-summarised only when its updated_at changed.
The parser is tolerant because the export format is not under our control; it was written without a real export.
"""

from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .llm import LLMOutputError, Provider, ProviderError
from .sessions import (
    ASSISTANT_MSG_CAP,
    MIN_CHARS,
    USER_MSG_CAP,
    ImportResult,
    Session,
    _load_state,
    _parse_ts,
    _save_state,
    build_card,
    redact_secrets,
    summarise,
)
from .store import Store

SOURCE = "claude-chat"


def load_conversations(path: Path) -> list[dict]:
    path = Path(path)
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            name = next((n for n in z.namelist() if n.endswith("conversations.json")), None)
            if name is None:
                return []
            data = json.loads(z.read(name).decode("utf-8", errors="replace"))
    else:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    return [c for c in data if isinstance(c, dict)] if isinstance(data, list) else []


def _msg_text(msg: dict) -> str:
    text = msg.get("text")
    if isinstance(text, str) and text.strip():
        return text
    content = msg.get("content")
    if isinstance(content, list):
        return "\n".join(b["text"] for b in content
                         if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str))
    return ""


def to_session(conv: dict) -> Session:
    lines: list[str] = []
    for msg in conv.get("chat_messages") or []:
        if not isinstance(msg, dict):
            continue
        sender = msg.get("sender")
        role = "USER" if sender == "human" else "ASSISTANT" if sender == "assistant" else None
        text = _msg_text(msg).strip()
        if role and text:
            lines.append(f"{role}: {redact_secrets(text[: USER_MSG_CAP if role == 'USER' else ASSISTANT_MSG_CAP])}")
    fallback = datetime.now(timezone.utc)
    started = _parse_ts(conv.get("created_at")) or fallback
    ended = _parse_ts(conv.get("updated_at")) or started
    name = conv.get("name")
    return Session(
        session_id=str(conv.get("uuid") or "unknown"),
        title=redact_secrets(name.strip()) if isinstance(name, str) and name.strip() else None,
        started_at=started,
        ended_at=ended,
        text="\n".join(lines),
        turns=len(lines),
    )


def _exports(drop_dir: Path) -> list[Path]:
    drop_dir = Path(drop_dir)
    if not drop_dir.is_dir():
        return []
    files = [p for p in drop_dir.iterdir() if p.is_file() and p.suffix.lower() in (".zip", ".json")]
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)  # newest export first


def import_chats(drop_dir: Path, store: Store, state_path: Path, llm: Provider,
                 limit: int | None = None, now: datetime | None = None) -> ImportResult:
    if not llm.is_local:
        raise ValueError("chat summaries must use a local model (private data)")
    now = now or datetime.now(timezone.utc)
    state: dict[str, Any] = _load_state(state_path)
    result = ImportResult()
    attempted = 0
    for export in _exports(drop_dir):
        try:
            conversations = load_conversations(export)
        except (OSError, ValueError, zipfile.BadZipFile):
            result.failed += 1
            continue
        for conv in conversations:
            uuid = str(conv.get("uuid") or "")
            if not uuid:
                continue
            sig = {"updated_at": str(conv.get("updated_at") or "")}
            if state.get(uuid) == sig:
                result.skipped_unchanged += 1
                continue
            if limit is not None and attempted >= limit:
                break
            session = to_session(conv)
            if session.turns < 2 or len(session.text) < MIN_CHARS:
                state[uuid] = sig
                result.skipped_trivial += 1
                continue
            attempted += 1
            try:
                summary = summarise(session, llm)
                store.write_card(build_card(session, summary, llm.name, now, id_prefix="ch", source=SOURCE,
                                              card_type="thought"))
            except (LLMOutputError, ProviderError, ValueError):
                result.failed += 1
                continue
            state[uuid] = sig
            result.imported += 1
    _save_state(state_path, state)
    return result
