from datetime import datetime, timezone
from pathlib import Path

import pytest

from secondbrain.adapters.takeout import WatchItem, parse_takeout

FIXTURE = Path(__file__).parent / "fixtures" / "watch-history.json"


def test_parses_normal_video():
    items = {i.video_id: i for i in parse_takeout(FIXTURE)}
    k8s = items["aaaaaaaaaaa"]
    assert k8s.title == "Kubernetes Networking Explained"
    assert k8s.url == "https://www.youtube.com/watch?v=aaaaaaaaaaa"
    assert k8s.channel == "Cloud Channel"
    assert k8s.watched_at.tzinfo is not None


def test_dedupes_keeping_latest():
    items = parse_takeout(FIXTURE)
    k8s = [i for i in items if i.video_id == "aaaaaaaaaaa"]
    assert len(k8s) == 1
    assert k8s[0].watched_at == datetime(2026, 11, 17, 8, 30, tzinfo=timezone.utc)


def test_skips_missing_url_ads_and_posts():
    items = parse_takeout(FIXTURE)
    assert len(items) == 2
    assert {i.video_id for i in items} == {"aaaaaaaaaaa", "bbbbbbbbbbb"}


def test_newest_first():
    items = parse_takeout(FIXTURE)
    assert [i.video_id for i in items] == ["aaaaaaaaaaa", "bbbbbbbbbbb"]


def test_unicode_title_preserved_and_extra_query_params_ignored():
    items = {i.video_id: i for i in parse_takeout(FIXTURE)}
    hindi = items["bbbbbbbbbbb"]
    assert hindi.title == "क्लाउड का परिचय 🚀 | DevOps हिंदी"
    assert hindi.channel == "हिंदी टेक"
    assert hindi.watched_at == datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)


def test_shorts_and_short_links_are_parsed(tmp_path: Path):
    f = tmp_path / "h.json"
    f.write_text(
        '[{"title":"Watched S","titleUrl":"https://www.youtube.com/shorts/ccccccccccc","time":"2026-11-17T01:00:00Z"},'
        '{"title":"Watched L","titleUrl":"https://youtu.be/ddddddddddd?t=5","time":"2026-11-17T02:00:00Z"}]',
        encoding="utf-8",
    )
    assert {i.video_id for i in parse_takeout(f)} == {"ccccccccccc", "ddddddddddd"}


def test_entry_with_bad_time_is_skipped_not_fatal(tmp_path: Path):
    f = tmp_path / "h.json"
    f.write_text(
        '[{"title":"Watched A","titleUrl":"https://www.youtube.com/watch?v=eeeeeeeeeee","time":"not a date"},'
        '{"title":"Watched B","titleUrl":"https://www.youtube.com/watch?v=fffffffffff","time":"2026-11-17T02:00:00Z"}]',
        encoding="utf-8",
    )
    assert [i.video_id for i in parse_takeout(f)] == ["fffffffffff"]


def test_malformed_file_raises_value_error_with_path(tmp_path: Path):
    f = tmp_path / "broken.json"
    f.write_text("{oops", encoding="utf-8")
    with pytest.raises(ValueError) as e:
        parse_takeout(f)
    assert "broken.json" in str(e.value)


def test_non_list_json_raises_value_error(tmp_path: Path):
    f = tmp_path / "obj.json"
    f.write_text('{"a": 1}', encoding="utf-8")
    with pytest.raises(ValueError):
        parse_takeout(f)


def test_watchitem_is_frozen():
    item = parse_takeout(FIXTURE)[0]
    with pytest.raises(Exception):
        item.title = "x"  # type: ignore[misc]
    assert isinstance(item, WatchItem)
