"""Regression tests for the findings of the independent review of retrieval v2 (Critical C1, Important I1-I6)."""

import json
import sqlite3
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pytest

import secondbrain.index as index_module
from secondbrain.advisor import build_context
from secondbrain.digest import refresh_digests
from secondbrain.embed import HashEmbedder
from secondbrain.index import Index
from secondbrain.schema import Card, KeyPoint, Topic
from secondbrain.store import Store

from test_digest import FakeLLM, IST, NOW, facts_reply, note, write_day, store  # noqa: F401  (store is a fixture)

WHEN = datetime(2026, 11, 17, 10, 0, tzinfo=timezone.utc)


def card(cid, text, source="telegram", channel=None):
    return Card(id=cid, source=source, type="thought", title=text[:50], consumed_at=WHEN, topic=Topic(primary="uncertain"),
                channel=channel, key_points=[KeyPoint(text=text, topic="uncertain", confidence=1.0)])


class ZeroEmbedder:
    """Every vector is zero: cosine contributes nothing, so only keyword search can find a note."""
    name = "zero"

    def embed(self, texts):
        return [[0.0] * 8 for _ in texts]


# --- C1: a deleted and rebuilt index must not be confused with the old one ----------------------------------------

def test_c1_bot_cache_does_not_survive_the_index_file_being_replaced(tmp_path: Path):
    store = Store(tmp_path / "brain")
    db = tmp_path / "brain" / "index" / "brain.db"
    store.write_card(card("tg_x1", "old public note about kubernetes basics"))
    store.write_card(card("tg_x2", "another old public note about terraform basics"))
    builder = Index(db, HashEmbedder())
    builder.rebuild(store)
    bot = Index(db, HashEmbedder())
    assert bot.search("kubernetes")                                   # the long-running bot warms its cache
    for p in list((tmp_path / "brain" / "index").glob("brain.db*")) + list((tmp_path / "brain" / "cards").rglob("*.json")):
        p.unlink()                                                    # someone deletes the index and the old cards
    store.write_card(card("tg_p", "private diary line about my money fears", channel="local-only"))
    store.write_card(card("tg_q", "open diary note about my money plans"))
    Index(db, HashEmbedder()).rebuild(store)                          # `sb index` rebuilds; row ids restart at 1
    hits = bot.search("diary money", include_local_only=False)
    assert [h.card_id for h in hits] == ["tg_q"]                      # the new data, and the private note NOT leaked
    assert all("private diary" not in h.snippet for h in hits)


# --- I1: filters must apply before the keyword shortlist is cut -----------------------------------------------------

def test_i1_keyword_shortlist_is_filtered_by_source_before_the_limit(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(index_module, "FTS_CANDIDATES", 5)
    store = Store(tmp_path / "brain")
    for i in range(12):
        store.write_card(card(f"cc_{i}", "deployment pipeline fix again", source="claude-code"))
    store.write_card(card("tg_note", "my deployment pipeline note", source="telegram"))
    index = Index(tmp_path / "i.db", ZeroEmbedder())
    index.rebuild(store)
    hits = index.search("deployment pipeline", sources=frozenset({"telegram"}))
    assert [h.card_id for h in hits] == ["tg_note"]
    assert index.search("deployment pipeline", sources=frozenset()) == []


def test_i1_keyword_shortlist_is_filtered_for_local_only_before_the_limit(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(index_module, "FTS_CANDIDATES", 5)
    store = Store(tmp_path / "brain")
    for i in range(12):
        store.write_card(card(f"tg_secret{i}", "private worry about money again", channel="local-only"))
    store.write_card(card("tg_open", "an open note about money"))
    index = Index(tmp_path / "i.db", ZeroEmbedder())
    index.rebuild(store)
    assert [h.card_id for h in index.search("money worry", include_local_only=False)] == ["tg_open"]


# --- I2: no index must not mean no evidence ----------------------------------------------------------------------------

def test_i2_pack_falls_back_to_keywords_when_the_index_file_is_missing(tmp_path: Path):
    store = Store(tmp_path / "brain")
    store.write_card(card("tg_old", "I never ask recruiters for anything because rejection hurts").model_copy(
        update={"consumed_at": NOW - timedelta(days=60)}))
    missing = Index(tmp_path / "does-not-exist.db", HashEmbedder())
    pack = build_context(store, "recruiters rejection", "goals", NOW, index=missing)
    assert "recruiters" in pack and "(nothing matched)" not in pack


# --- I3: a day the model keeps failing on must not block the rest -----------------------------------------------------------

def test_i3_a_failing_day_is_not_retried_until_it_changes_and_does_not_block_later_days(store):
    write_day(store, day=date(2026, 11, 14), prefix="a")
    write_day(store, day=date(2026, 11, 15), prefix="b")
    calls = {"bad": 0}

    def model(prompt):
        if "written on 2026-11-14" in prompt:
            calls["bad"] += 1
            return "garbage, not json"
        return facts_reply(prompt)

    llm = FakeLLM(model)
    first = refresh_digests(store, llm, NOW, max_calls=1)
    assert first.failed == 1 and calls["bad"] >= 1
    after_first = calls["bad"]                                            # (the JSON helper retries a bad reply once)
    second = refresh_digests(store, llm, NOW, max_calls=1)
    assert calls["bad"] == after_first and second.created == ["dgd_20261115"]   # not retried; the next day is served
    store.write_card(note("a_late", "one more note about that day", day=date(2026, 11, 14), hour=20))
    refresh_digests(store, llm, NOW, max_calls=1)
    assert calls["bad"] > after_first                                     # the day changed: tried again


# --- I4: a digest must not keep text of notes that are gone or private --------------------------------------------------

def test_i4_digest_is_removed_when_a_source_note_becomes_local_only_and_cascades_to_the_week(store):
    llm = FakeLLM(facts_reply)
    write_day(store, day=date(2026, 11, 2), prefix="a")
    write_day(store, day=date(2026, 11, 4), prefix="b")
    refresh_digests(store, llm, NOW, max_calls=10)
    assert store.has("dgd_20261102") and store.has("dgw_20261102")
    secret = store.read_card("a_02_0").model_copy(update={"channel": "local-only"})
    store.write_card(secret)                                              # one source note is now private
    refresh_digests(store, FakeLLM(RuntimeError("model down")), NOW, max_calls=10)   # even if regeneration fails
    assert not store.has("dgd_20261102") and not store.has("dgw_20261102")
    assert store.has("dgd_20261104")                                      # the untouched day keeps its digest


def test_i4_digest_is_removed_when_the_day_drops_below_the_minimum(store):
    llm = FakeLLM(facts_reply)
    write_day(store, day=date(2026, 11, 14), prefix="a", n=3)
    refresh_digests(store, llm, NOW)
    assert store.has("dgd_20261114")
    for p in list(store.iter_card_files()):
        if "a_14_2" in p.name:
            p.unlink()
    refresh_digests(store, llm, NOW)
    assert not store.has("dgd_20261114")


# --- I5: the living profile only runs when he switches it on ------------------------------------------------------------------

def test_i5_sync_does_not_write_the_living_profile_unless_enabled(tmp_path: Path):
    from secondbrain.cli import run_sync_command
    from secondbrain.config import load_settings
    from secondbrain.llm import Router
    from test_cli_digest import model, router_with

    for env, expect_line, expect_file in (({}, "profile: off", False), ({"SB_LIVING_PROFILE": "on"}, "profile: ok", True)):
        root = tmp_path / ("on" if env else "off")
        settings = load_settings(root=root, env=env)
        st = Store(root)
        st.write_card(Card(id="dgw_20261109", source="digest", type="thought", title="Week", consumed_at=NOW,
                           topic=Topic(primary="uncertain"),
                           key_points=[KeyPoint(text="He applied to jobs.", topic="uncertain", confidence=1.0)]))
        empty = root / "projects"
        empty.mkdir(parents=True)
        run_sync_command(settings, router_with(model), empty, 1, now=lambda: NOW)
        line = (settings.raw_dir / "sync.log").read_text(encoding="utf-8").strip().splitlines()[-1]
        assert expect_line in line and settings.living_profile_path.exists() is expect_file


def test_i5_digest_command_only_touches_the_profile_when_asked(tmp_path: Path):
    from secondbrain.cli import run_digest_command
    from secondbrain.config import load_settings
    from test_cli_digest import FnProvider, model

    settings = load_settings(root=tmp_path, env={})
    st = Store(tmp_path)
    st.write_card(Card(id="dgw_20261109", source="digest", type="thought", title="Week", consumed_at=NOW,
                       topic=Topic(primary="uncertain"), key_points=[KeyPoint(text="x", topic="uncertain", confidence=1.0)]))
    lines: list[str] = []
    run_digest_command(settings, FnProvider(model), NOW, out=lines.append)
    assert not settings.living_profile_path.exists() and not any(l.startswith("profile:") for l in lines)


# --- I6: embedding must not happen while the write lock is held ------------------------------------------------------------------

def test_i6_rebuild_does_not_hold_the_write_lock_while_embedding(tmp_path: Path):
    store = Store(tmp_path / "brain")
    for i in range(3):
        store.write_card(card(f"tg_{i}", f"note number {i} about plans and habits"))
    db = tmp_path / "brain" / "index" / "brain.db"

    class Spy:
        name = "spy"
        free = []

        def embed(self, texts):
            other = sqlite3.connect(db, timeout=0.3)        # the bot, wanting to write while the sync embeds
            try:
                other.execute("BEGIN IMMEDIATE")
                other.execute("ROLLBACK")
                Spy.free.append(True)
            finally:
                other.close()
            return [[1.0, 0.0, 0.0] for _ in texts]

    Index(db, Spy()).rebuild(store)
    assert Spy.free and all(Spy.free)
