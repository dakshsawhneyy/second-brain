"""Fetch, cache and chunk YouTube transcripts."""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
PREFERRED_LANGUAGES = ("en", "en-US", "en-GB", "hi")


class TranscriptUnavailable(Exception):
    """No transcript exists for this video (disabled, removed, none in our languages)."""


class RateLimited(Exception):
    """YouTube is throttling or blocking us (or the network is down); stop the run and retry later."""


class TranscriptError(Exception):
    """This one video's transcript could not be fetched or parsed. Skip it, record it, keep going."""


@dataclass(frozen=True)
class Segment:
    start: float
    text: str


@dataclass(frozen=True)
class Transcript:
    video_id: str
    language: str
    segments: list[Segment]


def _default_fetcher(video_id: str) -> Transcript:
    import requests
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api import _errors as err

    unavailable = (
        err.TranscriptsDisabled, err.NoTranscriptFound, err.VideoUnavailable,
        err.VideoUnplayable, err.AgeRestricted, err.InvalidVideoId,
    )
    throttled = (err.IpBlocked, err.RequestBlocked, err.PoTokenRequired, requests.ConnectionError, requests.Timeout)
    try:
        fetched = YouTubeTranscriptApi().fetch(video_id, languages=PREFERRED_LANGUAGES)
    except unavailable as e:
        raise TranscriptUnavailable(type(e).__name__) from e
    except throttled as e:
        raise RateLimited(type(e).__name__) from e
    except (err.YouTubeTranscriptApiException, requests.RequestException) as e:
        # anything else (unparsable page, consent cookie, plain HTTP errors): this video only
        raise TranscriptError(type(e).__name__) from e
    segments = [Segment(float(s.start), s.text) for s in fetched]
    return Transcript(video_id=video_id, language=getattr(fetched, "language_code", "en"), segments=segments)


def _cache_path(cache_dir: Path, video_id: str) -> Path:
    return Path(cache_dir) / "transcripts" / f"{video_id}.json"


_MISS = object()


def _read_cache(path: Path, video_id: str):
    """Return a Transcript, None (cached 'unavailable'), or _MISS."""
    if not path.is_file():
        return _MISS
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("unavailable") is True:
            return None
        segs = [Segment(float(s), str(t)) for s, t in data["segments"]]
        return Transcript(video_id=data["video_id"], language=data["language"], segments=segs)
    except (ValueError, KeyError, TypeError, OSError):
        return _MISS


def _write_cache(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def get_transcript(
    video_id: str,
    cache_dir: Path,
    fetcher: Callable[[str], Transcript] | None = None,
    max_retries: int = 2,
    sleep: Callable[[float], None] = time.sleep,
) -> Transcript | None:
    """Transcript, or None when YouTube has none. Raises RateLimited when throttled after all retries."""
    if not _VIDEO_ID.match(video_id):
        raise ValueError(f"invalid video id: {video_id!r}")
    path = _cache_path(cache_dir, video_id)
    cached = _read_cache(path, video_id)
    if cached is not _MISS:
        return cached

    fetch = fetcher or _default_fetcher
    for attempt in range(max_retries + 1):
        try:
            t = fetch(video_id)
        except TranscriptUnavailable:
            _write_cache(path, {"unavailable": True})
            return None
        except RateLimited:
            if attempt >= max_retries:
                raise  # transient: not cached, and the caller must tell it apart from "no transcript"
            sleep(2**attempt)
            continue
        _write_cache(path, {
            "video_id": t.video_id,
            "language": t.language,
            "segments": [[s.start, s.text] for s in t.segments],
        })
        return t
    return None


def _stamp(seconds: float) -> str:
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _line(seg: Segment, with_times: bool) -> str:
    return f"[{_stamp(seg.start)}] {seg.text}" if with_times else seg.text


def to_text(t: Transcript, with_times: bool = False) -> str:
    return ("\n" if with_times else " ").join(_line(s, with_times) for s in t.segments)


def chunk(t: Transcript, max_chars: int = 24000, with_times: bool = True) -> list[str]:
    sep = "\n" if with_times else " "
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for seg in t.segments:
        line = _line(seg, with_times)
        added = len(line) + (len(sep) if current else 0)
        if current and size + added > max_chars:
            chunks.append(sep.join(current))
            current, size = [], 0
            added = len(line)
        current.append(line)
        size += added
    if current:
        chunks.append(sep.join(current))
    return chunks
