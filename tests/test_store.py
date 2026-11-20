import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from secondbrain.schema import Card, Tombstone
from secondbrain.store import Store


def make_card(id="yt_abc", when=datetime(2026, 11, 17, 10, 0, tzinfo=timezone.utc), **over) -> Card:
    base = dict(id=id, source="youtube", type="consumed", title="T", consumed_at=when,
                topic={"primary": "infra/sre", "secondary": []})
    base.update(over)
    return Card(**base)


def make_tomb(id="yt_t1") -> Tombstone:
    return Tombstone(id=id, source="youtube", title="x", url=None, date="2026-11-17", topic="noise/entertainment", score=5)


def test_write_card_creates_dated_path(tmp_path: Path):
    s = Store(tmp_path)
    p = s.write_card(make_card())
    assert p == tmp_path / "cards" / "2026" / "11" / "yt_abc.json"
    assert json.loads(p.read_text(encoding="utf-8"))["id"] == "yt_abc"


def test_write_card_is_atomic(tmp_path: Path, monkeypatch):
    s = Store(tmp_path)

    def boom(*a, **k):
        raise OSError("disk exploded")

    monkeypatch.setattr("secondbrain.store.os.replace", boom)
    with pytest.raises(OSError):
        s.write_card(make_card())
    month = tmp_path / "cards" / "2026" / "11"
    assert not (month / "yt_abc.json").exists()
    assert list(month.glob("*")) == []  # no .tmp left behind


def test_write_card_overwrites_same_id(tmp_path: Path):
    s = Store(tmp_path)
    s.write_card(make_card(title="one"))
    s.write_card(make_card(title="two"))
    assert s.read_card("yt_abc").title == "two"
    assert len(list(s.iter_cards())) == 1


def test_write_tombstone_twice_one_line(tmp_path: Path):
    s = Store(tmp_path)
    s.write_tombstone(make_tomb())
    s.write_tombstone(make_tomb())
    lines = (tmp_path / "archive" / "tombstones.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1


def test_has_true_for_card_and_tombstone_false_otherwise(tmp_path: Path):
    s = Store(tmp_path)
    s.write_card(make_card())
    s.write_tombstone(make_tomb())
    assert s.has("yt_abc") and s.has("yt_t1")
    assert not s.has("yt_missing")


def test_has_sees_tombstones_written_by_another_store_instance(tmp_path: Path):
    Store(tmp_path).write_tombstone(make_tomb())
    assert Store(tmp_path).has("yt_t1")


def test_iter_cards_roundtrip_across_months(tmp_path: Path):
    s = Store(tmp_path)
    s.write_card(make_card("yt_a", datetime(2026, 10, 1, tzinfo=timezone.utc)))
    s.write_card(make_card("yt_b", datetime(2026, 11, 2, tzinfo=timezone.utc)))
    assert [c.id for c in s.iter_cards()] == ["yt_a", "yt_b"]


def test_read_missing_card_raises_key_error(tmp_path: Path):
    with pytest.raises(KeyError):
        Store(tmp_path).read_card("nope")


def test_unicode_title_roundtrip(tmp_path: Path):
    s = Store(tmp_path)
    s.write_card(make_card(title="नमस्ते 🚀 क्लाउड"))
    assert s.read_card("yt_abc").title == "नमस्ते 🚀 क्लाउड"


def test_corrupt_card_file_is_skipped_by_iter_not_fatal(tmp_path: Path):
    s = Store(tmp_path)
    s.write_card(make_card("yt_ok"))
    bad = tmp_path / "cards" / "2026" / "11" / "yt_bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert [c.id for c in s.iter_cards()] == ["yt_ok"]
    assert s.corrupt_files == [bad]
