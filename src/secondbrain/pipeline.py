"""Idempotent ingest: watch items -> triage -> (tombstone | extract -> card)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from .adapters.takeout import WatchItem
from .extract import extract
from .llm import LLMOutputError, ProviderError, Router
from .schema import Card, Provenance, Relevance, Tombstone, Topic
from .store import Store
from .transcripts import RateLimited, Transcript, TranscriptError, get_transcript, to_text
from .triage import TRANSCRIPT_HEAD_CHARS, triage


@dataclass
class IngestReport:
    new_cards: int = 0
    tombstones: int = 0
    skipped_existing: int = 0
    failures: list[tuple[str, str]] = field(default_factory=list)


def _secondary_topics(key_points, primary: str) -> list[str]:
    counts = Counter(k.topic for k in key_points if k.topic not in (primary, "uncertain"))
    return [topic for topic, _ in counts.most_common(2)]


def run_ingest(
    items: Sequence[WatchItem],
    store: Store,
    router: Router,
    goals_text: str,
    cache_dir: Path,
    fetch: Callable[[str, Path], Transcript | None] = get_transcript,
    limit: int | None = None,
    now: Callable[[], datetime] | None = None,
) -> IngestReport:
    """Process new items. Safe to re-run: existing cards and tombstones are skipped without any LLM call.

    Triage prompts contain the user's goals, so triage is routed as private (local models only).
    Extraction prompts carry no personal context and may use a free cloud model.
    """
    now = now or (lambda: datetime.now(timezone.utc))
    triage_llm = router.route("triage", "private")
    extract_llm = router.route("extract", "public")
    report = IngestReport()

    for item in items:
        if limit is not None and report.new_cards + report.tombstones >= limit:
            break
        card_id = f"yt_{item.video_id}"
        if store.has(card_id):
            report.skipped_existing += 1
            continue
        try:
            transcript = fetch(item.video_id, cache_dir)
            has_text = transcript is not None and bool(transcript.segments)
            head = to_text(transcript)[:TRANSCRIPT_HEAD_CHARS] if has_text else None
            tri = triage(item, head, goals_text, triage_llm)

            if not tri.keep:
                store.write_tombstone(Tombstone(
                    id=card_id, source="youtube", title=item.title, url=item.url,
                    date=item.watched_at.date(), topic=tri.topic, score=tri.score,
                ))
                report.tombstones += 1
                continue

            key_points, action = [], None
            if has_text:
                extraction = extract(item, transcript, extract_llm)
                key_points, action = extraction.key_points, extraction.action

            store.write_card(Card(
                id=card_id, source="youtube", type="consumed", title=item.title, url=item.url,
                channel=item.channel, consumed_at=item.watched_at,
                topic=Topic(primary=tri.topic, secondary=_secondary_topics(key_points, tri.topic)),
                format=tri.format,
                relevance=Relevance(bet_job=tri.sub.bet_job, bet_product=tri.sub.bet_product,
                                    actionability=tri.sub.actionability, novelty=tri.sub.novelty,
                                    quality=tri.sub.quality, score=tri.score),
                key_points=key_points, action=action,
                provenance=Provenance(transcript="captions" if has_text else "none",
                                      model=(extract_llm if has_text else triage_llm).name,
                                      processed_at=now()),
            ))
            report.new_cards += 1
        except RateLimited:
            report.failures.append((card_id, "rate limited by YouTube; stopping this run, retry later"))
            break
        except (LLMOutputError, ProviderError, ValidationError, TranscriptError) as e:
            report.failures.append((card_id, f"{type(e).__name__}: {str(e)[:200]}"))
    return report
