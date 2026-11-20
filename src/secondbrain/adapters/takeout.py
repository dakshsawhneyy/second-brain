"""Google Takeout YouTube watch-history.json -> WatchItem list."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


@dataclass(frozen=True)
class WatchItem:
    video_id: str
    title: str
    url: str
    channel: str | None
    watched_at: datetime


def _video_id(url: str) -> str | None:
    p = urlparse(url)
    host = p.netloc.lower()
    for prefix in ("www.", "m.", "music."):
        host = host.removeprefix(prefix)
    vid: str | None = None
    if host == "youtube.com":
        if p.path == "/watch":
            vid = (parse_qs(p.query).get("v") or [None])[0]
        elif p.path.startswith("/shorts/"):
            parts = p.path.split("/")
            vid = parts[2] if len(parts) > 2 else None
    elif host == "youtu.be":
        vid = p.path.lstrip("/").split("/")[0] or None
    return vid if vid and _VIDEO_ID.match(vid) else None


def _parse_time(raw: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _is_ad(entry: dict) -> bool:
    return any(str(d.get("name", "")).startswith("From Google Ads") for d in entry.get("details") or [])


def parse_takeout(path: Path) -> list[WatchItem]:
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"{path}: not valid JSON ({e})") from e
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected a JSON list of watch-history entries")

    latest: dict[str, WatchItem] = {}
    for entry in data:
        if not isinstance(entry, dict) or _is_ad(entry):
            continue
        url = entry.get("titleUrl")
        if not url:
            continue
        vid = _video_id(url)
        watched_at = _parse_time(entry.get("time", ""))
        if vid is None or watched_at is None:
            continue
        title = str(entry.get("title", "")).removeprefix("Watched ").strip()
        subtitles = entry.get("subtitles") or []
        channel = subtitles[0].get("name") if subtitles and isinstance(subtitles[0], dict) else None
        item = WatchItem(video_id=vid, title=title, url=f"https://www.youtube.com/watch?v={vid}",
                         channel=channel, watched_at=watched_at)
        if vid not in latest or item.watched_at > latest[vid].watched_at:
            latest[vid] = item
    return sorted(latest.values(), key=lambda i: i.watched_at, reverse=True)
