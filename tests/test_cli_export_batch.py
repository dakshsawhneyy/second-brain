import json
from datetime import datetime, timezone
from pathlib import Path

from secondbrain.adapters.takeout import WatchItem
from secondbrain.cli import build_parser, export_batch
from secondbrain.transcripts import Segment, Transcript


def make_items(n: int) -> list[WatchItem]:
    return [
        WatchItem(video_id=f"vid{i:08d}", title=f"Video {i}", url=f"https://www.youtube.com/watch?v=vid{i:08d}",
                  channel="Chan", watched_at=datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc))
        for i in range(n)
    ]


def fake_fetch_factory(missing: set[str], lengths: dict[str, int]):
    calls: list[str] = []

    def fetch(video_id: str, cache_dir: Path):
        calls.append(video_id)
        if video_id in missing:
            return None
        size = lengths.get(video_id, 100)
        return Transcript(video_id=video_id, language="en",
                          segments=[Segment(0.0, "w" * size), Segment(float(size), "end")])

    fetch.calls = calls  # type: ignore[attr-defined]
    return fetch


def test_export_batch_exports_n_files_plus_manifest_and_skips_missing(tmp_path: Path):
    items = make_items(12)
    missing = {items[3].video_id, items[7].video_id}
    fetch = fake_fetch_factory(missing, {})
    paths = export_batch(items, n=10, out=tmp_path / "out", cache_dir=tmp_path / "raw", fetch=fetch)
    assert len(paths) == 10
    assert all(p.suffix == ".txt" and p.is_file() for p in paths)
    manifest = json.loads((tmp_path / "out" / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest) == 10
    assert {m["video_id"] for m in manifest}.isdisjoint(missing)
    assert set(manifest[0]) == {"video_id", "title", "minutes", "chars"}


def test_export_batch_picks_mixed_lengths_including_shortest_and_longest(tmp_path: Path):
    items = make_items(14)
    lengths = {it.video_id: 100 * (i + 1) for i, it in enumerate(items)}
    missing = {items[0].video_id, items[1].video_id}
    fetch = fake_fetch_factory(missing, lengths)
    export_batch(items, n=5, out=tmp_path / "out", cache_dir=tmp_path / "raw", fetch=fetch)
    manifest = json.loads((tmp_path / "out" / "manifest.json").read_text(encoding="utf-8"))
    ids = {m["video_id"] for m in manifest}
    assert len(manifest) == 5
    assert items[2].video_id in ids   # shortest with a transcript
    assert items[13].video_id in ids  # longest


def test_export_batch_limits_fetch_attempts(tmp_path: Path):
    items = make_items(50)
    fetch = fake_fetch_factory(set(), {})
    export_batch(items, n=4, out=tmp_path / "out", cache_dir=tmp_path / "raw", fetch=fetch)
    assert len(fetch.calls) <= 12  # 3 * n, be polite to YouTube


def test_export_batch_with_fewer_candidates_than_n_exports_what_it_has(tmp_path: Path):
    items = make_items(3)
    paths = export_batch(items, n=10, out=tmp_path / "out", cache_dir=tmp_path / "raw", fetch=fake_fetch_factory(set(), {}))
    assert len(paths) == 3


def test_export_batch_stops_politely_when_rate_limited_and_keeps_progress(tmp_path: Path):
    from secondbrain.transcripts import RateLimited

    items = make_items(10)
    good = fake_fetch_factory(set(), {})

    def fetch(video_id: str, cache_dir: Path):
        if video_id == items[3].video_id:
            raise RateLimited()
        return good(video_id, cache_dir)

    paths = export_batch(items, n=10, out=tmp_path / "out", cache_dir=tmp_path / "raw", fetch=fetch)
    assert len(paths) == 3  # items 0-2 fetched before the block; nothing after it was attempted
    assert (tmp_path / "out" / "manifest.json").is_file()


def test_export_batch_skips_a_video_whose_transcript_cannot_be_parsed(tmp_path: Path):
    from secondbrain.transcripts import TranscriptError

    items = make_items(6)
    good = fake_fetch_factory(set(), {})

    def fetch(video_id: str, cache_dir: Path):
        if video_id == items[2].video_id:
            raise TranscriptError("YouTubeDataUnparsable")
        return good(video_id, cache_dir)

    paths = export_batch(items, n=6, out=tmp_path / "out", cache_dir=tmp_path / "raw", fetch=fetch)
    assert len(paths) == 5 and not any(items[2].video_id in p.name for p in paths)


def test_export_batch_empty_items_returns_empty_and_writes_empty_manifest(tmp_path: Path):
    paths = export_batch([], n=5, out=tmp_path / "out", cache_dir=tmp_path / "raw", fetch=fake_fetch_factory(set(), {}))
    assert paths == []
    assert json.loads((tmp_path / "out" / "manifest.json").read_text(encoding="utf-8")) == []


def test_parser_export_batch_arguments():
    args = build_parser().parse_args(["export-batch", "--takeout", "t.json", "--n", "7", "--out", "o"])
    assert args.command == "export-batch"
    assert args.takeout == Path("t.json") and args.n == 7 and args.out == Path("o")
