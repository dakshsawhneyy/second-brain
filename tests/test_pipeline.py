import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from secondbrain.adapters.takeout import WatchItem
from secondbrain.llm import Router, SensitivityError
from secondbrain.pipeline import IngestReport, run_ingest
from secondbrain.store import Store
from secondbrain.transcripts import RateLimited, Segment, Transcript

GOALS = "PRIVATE-GOALS: remote infra role, own product."
BASE = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)

TRIAGE = {
    "keep": {"topic": "infra/sre", "format": "tutorial", "bet_job": 9, "bet_product": 2, "actionability": 7, "novelty": 6, "quality": 8},
    "ent": {"topic": "noise/entertainment", "format": "review", "bet_job": 9, "bet_product": 9, "actionability": 9, "novelty": 9, "quality": 9},
}


class FnProvider:
    def __init__(self, fn, is_local=True, name="fake"):
        self.fn, self.is_local, self.name, self.calls = fn, is_local, name, []

    def complete(self, prompt, *, system=None):
        self.calls.append(prompt)
        return self.fn(prompt)


def triage_fn(prompt: str) -> str:
    if "BROKEN-TRIAGE" in prompt:
        return "garbage"
    kind = "ent" if "ENT" in prompt else "keep"
    return json.dumps(TRIAGE[kind])


def extract_fn(prompt: str) -> str:
    if "BROKEN-EXTRACT" in prompt:
        return "garbage"
    pts = [
        {"text": "p1", "topic": "ai/agents", "t": "00:10", "confidence": 0.9},
        {"text": "p2", "topic": "ai/agents", "t": "00:20", "confidence": 0.8},
        {"text": "p3", "topic": "business/product", "t": "00:30", "confidence": 0.7},
        {"text": "p4", "topic": "infra/sre", "t": None, "confidence": 0.6},
    ]
    return json.dumps({"key_points": pts, "action": "Try an agent today"})


def item(i: int, title: str) -> WatchItem:
    vid = f"vid{i:08d}"
    return WatchItem(video_id=vid, title=title, url=f"https://www.youtube.com/watch?v={vid}", channel="Chan",
                     watched_at=BASE - timedelta(minutes=i))


def good_fetch(video_id: str, cache_dir: Path):
    return Transcript(video_id=video_id, language="en", segments=[Segment(0.0, "hello world"), Segment(30.0, "more")])


def setup(tmp_path: Path, triage_local=True, extract_local=True):
    store = Store(tmp_path / "brain")
    tri = FnProvider(triage_fn, is_local=triage_local, name="triage-fake")
    ext = FnProvider(extract_fn, is_local=extract_local, name="extract-fake")
    return store, Router({"triage": tri, "extract": ext}), tri, ext


def run(items, store, router, tmp_path, fetch=good_fetch, **kw) -> IngestReport:
    return run_ingest(items, store, router, GOALS, tmp_path / "raw", fetch=fetch, **kw)


def test_second_run_makes_no_new_cards_and_no_llm_calls(tmp_path: Path):
    store, router, tri, ext = setup(tmp_path)
    items = [item(0, "keep A"), item(1, "ENT B")]
    first = run(items, store, router, tmp_path)
    calls_after_first = (len(tri.calls), len(ext.calls))
    second = run(items, store, router, tmp_path)
    assert (first.new_cards, first.tombstones) == (1, 1)
    assert (second.new_cards, second.tombstones, second.skipped_existing) == (0, 0, 2)
    assert (len(tri.calls), len(ext.calls)) == calls_after_first


def test_low_score_item_becomes_tombstone_without_extract_call(tmp_path: Path):
    store, router, tri, ext = setup(tmp_path)
    rep = run([item(0, "ENT clip")], store, router, tmp_path)
    assert rep.tombstones == 1 and rep.new_cards == 0
    assert ext.calls == []
    assert store.has("yt_vid00000000")
    line = json.loads((tmp_path / "brain" / "archive" / "tombstones.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert line["topic"] == "noise/entertainment" and line["score"] == 20


def test_missing_transcript_keeper_gets_card_with_provenance_none(tmp_path: Path):
    store, router, tri, ext = setup(tmp_path)
    rep = run([item(0, "keep A")], store, router, tmp_path, fetch=lambda v, c: None)
    card = store.read_card("yt_vid00000000")
    assert rep.new_cards == 1
    assert card.provenance.transcript == "none" and card.key_points == []
    assert ext.calls == []


def test_keeper_card_fields(tmp_path: Path):
    store, router, tri, ext = setup(tmp_path)
    run([item(0, "keep A")], store, router, tmp_path, now=lambda: BASE)
    c = store.read_card("yt_vid00000000")
    assert (c.id, c.source, c.type, c.visibility, c.tier) == ("yt_vid00000000", "youtube", "consumed", "private", "hot")
    assert c.topic.primary == "infra/sre"
    assert c.topic.secondary == ["ai/agents", "business/product"]  # by frequency, primary excluded, max 2
    assert c.format == "tutorial" and c.channel == "Chan" and c.url.endswith("vid00000000")
    assert c.relevance is not None and c.relevance.score == 80 and c.relevance.bet_job == 9
    assert len(c.key_points) == 4 and c.action is not None and c.action.text == "Try an agent today"
    assert c.provenance.transcript == "captions" and c.provenance.model == "extract-fake"
    assert c.provenance.processed_at == BASE and c.consumed_at == BASE


def test_one_failing_item_does_not_stop_the_run(tmp_path: Path):
    store, router, tri, ext = setup(tmp_path)
    items = [item(0, "keep A"), item(1, "BROKEN-TRIAGE thing"), item(2, "keep C")]
    rep = run(items, store, router, tmp_path)
    assert rep.new_cards == 2
    assert len(rep.failures) == 1 and rep.failures[0][0] == "yt_vid00000001"
    assert not store.has("yt_vid00000001")  # not written, so it will be retried next run


def test_unparsable_transcript_is_a_per_item_failure_and_the_run_continues(tmp_path: Path):
    from secondbrain.transcripts import TranscriptError

    store, router, tri, ext = setup(tmp_path)

    def fetch(video_id: str, cache_dir: Path):
        if video_id == "vid00000001":
            raise TranscriptError("YouTubeDataUnparsable")
        return good_fetch(video_id, cache_dir)

    rep = run([item(0, "keep A"), item(1, "keep B"), item(2, "keep C")], store, router, tmp_path, fetch=fetch)
    assert rep.new_cards == 2
    assert [f[0] for f in rep.failures] == ["yt_vid00000001"] and "TranscriptError" in rep.failures[0][1]
    assert not store.has("yt_vid00000001")


def test_extract_failure_leaves_item_unwritten_for_retry(tmp_path: Path):
    store, router, tri, ext = setup(tmp_path)
    rep = run([item(0, "keep BROKEN-EXTRACT")], store, router, tmp_path)
    assert rep.new_cards == 0 and len(rep.failures) == 1
    assert not store.has("yt_vid00000000")


def test_interrupted_run_resumes_without_duplicates_or_temp_files(tmp_path: Path):
    store, router, tri, ext = setup(tmp_path)
    items = [item(i, f"keep {i}") for i in range(5)]

    def flaky(video_id: str, cache_dir: Path):
        if video_id == "vid00000002":
            raise KeyboardInterrupt
        return good_fetch(video_id, cache_dir)

    with pytest.raises(KeyboardInterrupt):
        run(items, store, router, tmp_path, fetch=flaky)
    assert list((tmp_path / "brain").rglob("*.tmp")) == []
    triage_calls_before = len(tri.calls)
    rep = run(items, store, router, tmp_path)
    assert rep.skipped_existing == 2 and rep.new_cards == 3
    assert len(list(store.iter_cards())) == 5
    assert len(tri.calls) - triage_calls_before == 3  # finished items were not re-triaged


def test_limit_stops_after_n_new_items(tmp_path: Path):
    store, router, tri, ext = setup(tmp_path)
    items = [item(i, f"keep {i}") for i in range(6)]
    rep = run(items, store, router, tmp_path, limit=2)
    assert rep.new_cards == 2
    rep2 = run(items, store, router, tmp_path, limit=2)
    assert rep2.new_cards == 2 and rep2.skipped_existing == 2


def test_rate_limit_stops_run_keeps_progress_and_does_not_write_that_item(tmp_path: Path):
    store, router, tri, ext = setup(tmp_path)
    items = [item(i, f"keep {i}") for i in range(5)]

    def throttled(video_id: str, cache_dir: Path):
        if video_id == "vid00000002":
            raise RateLimited()
        return good_fetch(video_id, cache_dir)

    rep = run(items, store, router, tmp_path, fetch=throttled)
    assert rep.new_cards == 2
    assert [f[0] for f in rep.failures] == ["yt_vid00000002"] and "rate" in rep.failures[0][1].lower()
    assert not store.has("yt_vid00000002") and not store.has("yt_vid00000003")
    rep2 = run(items, store, router, tmp_path)
    assert rep2.new_cards == 3


def test_triage_is_never_routed_to_a_cloud_model(tmp_path: Path):
    store, router, tri, ext = setup(tmp_path, triage_local=False)
    with pytest.raises(SensitivityError):
        run([item(0, "keep A")], store, router, tmp_path)
    assert tri.calls == [] and list(store.iter_cards()) == []


def test_goals_reach_triage_but_never_the_extract_model(tmp_path: Path):
    store, router, tri, ext = setup(tmp_path, extract_local=False)  # extract may run on a cloud model
    run([item(0, "keep A")], store, router, tmp_path)
    assert all("PRIVATE-GOALS" in p for p in tri.calls) and tri.calls
    assert ext.calls and all("PRIVATE-GOALS" not in p for p in ext.calls)


def test_skipped_existing_counts_cards_and_tombstones(tmp_path: Path):
    store, router, tri, ext = setup(tmp_path)
    items = [item(0, "keep A"), item(1, "ENT B"), item(2, "keep C")]
    run(items, store, router, tmp_path)
    rep = run(items + [item(3, "keep D")], store, router, tmp_path)
    assert rep.skipped_existing == 3 and rep.new_cards == 1


def test_empty_items_is_a_noop(tmp_path: Path):
    store, router, tri, ext = setup(tmp_path)
    rep = run([], store, router, tmp_path)
    assert (rep.new_cards, rep.tombstones, rep.skipped_existing, rep.failures) == (0, 0, 0, [])
