import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from secondbrain.embed import HashEmbedder
from secondbrain.index import Hit, Index
from secondbrain.schema import Card, KeyPoint, Relevance
from secondbrain.store import Store

WHEN = datetime(2026, 11, 17, 10, 0, tzinfo=timezone.utc)


def card(id, title, points=(), source="youtube", score=50, tier="hot", topic="infra/sre") -> Card:
    return Card(
        id=id, source=source, type="consumed" if source == "youtube" else "book", title=title, consumed_at=WHEN,
        topic={"primary": topic, "secondary": []}, tier=tier,
        relevance=Relevance(bet_job=5, bet_product=5, actionability=5, novelty=5, quality=5, score=score),
        key_points=[KeyPoint(text=p, topic=topic, t=None, confidence=0.8) for p in points],
    )


@pytest.fixture
def env(tmp_path: Path):
    store = Store(tmp_path / "brain")
    index = Index(tmp_path / "brain" / "index" / "brain.db", HashEmbedder())
    return store, index


def test_sqlite_has_fts5():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE VIRTUAL TABLE t USING fts5(a)")  # raises if FTS5 is missing


def test_hash_embedder_is_deterministic_and_normalized():
    e = HashEmbedder()
    a, b = e.embed(["kubernetes networking"])[0], e.embed(["kubernetes networking"])[0]
    assert a == b
    assert math.isclose(sum(x * x for x in a), 1.0, rel_tol=1e-6)
    assert e.embed([""])[0] == [0.0] * 64


def test_rebuild_counts_cards_not_tombstones(env):
    store, index = env
    store.write_card(card("yt_a", "Kubernetes basics"))
    store.write_card(card("yt_b", "Terraform modules"))
    from secondbrain.schema import Tombstone
    store.write_tombstone(Tombstone(id="yt_t", source="youtube", title="x", date="2026-11-17", topic="noise/entertainment", score=5))
    assert index.rebuild(store) == 2


def test_search_finds_keyword_match_first(env):
    store, index = env
    store.write_card(card("yt_k8s", "Kubernetes networking explained", ["pods talk through services"]))
    store.write_card(card("yt_tf", "Terraform modules", ["split state per environment"]))
    index.rebuild(store)
    hits = index.search("kubernetes services")
    assert hits and hits[0].card_id == "yt_k8s"
    assert isinstance(hits[0], Hit) and hits[0].title == "Kubernetes networking explained"
    assert hits[0].snippet == "pods talk through services"


def test_higher_relevance_card_outranks_equal_text_match(env):
    store, index = env
    store.write_card(card("yt_low", "Pricing strategy for SaaS", score=20))
    store.write_card(card("yt_high", "Pricing strategy for SaaS", score=90))
    index.rebuild(store)
    assert [h.card_id for h in index.search("pricing strategy")][:2] == ["yt_high", "yt_low"]


def test_per_source_cap_enforced(env):
    store, index = env
    for i in range(6):
        store.write_card(card(f"yt_{i}", "startup pricing lesson", score=80))
    store.write_card(card("bk_1", "startup pricing in a book", source="book", score=10))
    index.rebuild(store)
    hits = index.search("startup pricing", k=6, per_source_cap=3)
    ids = [h.card_id for h in hits]
    assert sum(i.startswith("yt_") for i in ids) == 3
    assert "bk_1" in ids


def test_k_limits_results(env):
    store, index = env
    for i in range(5):
        store.write_card(card(f"yt_{i}", "devops lesson"))
    index.rebuild(store)
    assert len(index.search("devops", k=2, per_source_cap=10)) == 2


def test_rebuild_is_repeatable_after_deleting_db(env, tmp_path: Path):
    store, index = env
    store.write_card(card("yt_a", "Kubernetes basics"))
    assert index.rebuild(store) == 1
    (tmp_path / "brain" / "index" / "brain.db").unlink()
    assert index.rebuild(store) == 1
    assert index.search("kubernetes")[0].card_id == "yt_a"


def test_rebuild_drops_cards_that_no_longer_exist(env, tmp_path: Path):
    store, index = env
    store.write_card(card("yt_a", "Kubernetes basics"))
    index.rebuild(store)
    (tmp_path / "brain" / "cards" / "2026" / "11" / "yt_a.json").unlink()
    assert index.rebuild(store) == 0
    assert index.search("kubernetes") == []


def test_cold_tier_cards_are_not_indexed(env):
    store, index = env
    store.write_card(card("yt_cold", "Kubernetes basics", tier="cold"))
    assert index.rebuild(store) == 0


def test_search_on_empty_or_missing_index_returns_empty(env):
    store, index = env
    assert index.search("anything") == []  # db does not exist yet
    index.rebuild(store)
    assert index.search("anything") == []


@pytest.mark.parametrize("q", ['C++ "quote" AND OR * (', "", "   ", "!!!", "NEAR(", "a:b -c ^d"])
def test_search_with_special_characters_does_not_crash(env, q):
    store, index = env
    store.write_card(card("yt_a", "C++ memory model"))
    index.rebuild(store)
    index.search(q)  # must not raise


def test_cards_without_relevance_get_a_neutral_weight(env):
    store, index = env
    c = card("tg_1", "my note about pricing", source="telegram")
    store.write_card(c.model_copy(update={"relevance": None, "type": "thought"}))
    index.rebuild(store)
    assert index.search("pricing")[0].card_id == "tg_1"


@pytest.mark.slow
def test_real_fastembed_model_semantic_match(tmp_path: Path):
    from secondbrain.embed import FastEmbedder

    store = Store(tmp_path / "brain")
    store.write_card(card("yt_a", "How to deploy containers on Kubernetes"))
    store.write_card(card("yt_b", "Best pasta recipes"))
    index = Index(tmp_path / "brain" / "index" / "brain.db", FastEmbedder(cache_dir=tmp_path / "models"))
    index.rebuild(store)
    assert index.search("running docker workloads in a cluster")[0].card_id == "yt_a"


def test_related_only_returns_real_matches_and_skips_excluded(env):
    store, index = env
    store.write_card(card("yt_k8s", "Kubernetes networking explained", ["pods talk through services"]))
    store.write_card(card("yt_tf", "Terraform modules", ["split state per environment"]))
    index.rebuild(store)
    hits = index.related("kubernetes networking pods services", k=3, min_cosine=0.3)
    assert hits and hits[0].card_id == "yt_k8s"
    assert index.related("kubernetes networking pods services", k=3, min_cosine=0.3, exclude=frozenset({"yt_k8s"})) == [] or \
        all(h.card_id != "yt_k8s" for h in index.related("kubernetes networking pods services", 3, 0.3, frozenset({"yt_k8s"})))
    assert index.related("completely different cooking pasta", k=3, min_cosine=0.9) == []


def test_stopwords_alone_do_not_count_as_a_keyword_match(env):
    store, index = env
    store.write_card(card("yt_a", "My plan for the week", ["I will go to the gym"]))
    index.rebuild(store)
    # "my" and "the" are stopwords: the card must not get a keyword score from them
    hits = index.search("my the")
    assert all(h.score < 0.5 for h in hits)


def test_reply_context_is_searchable_with_the_answer(env):
    store, index = env
    c = card("tg_r", "Yes", ["Yes"]).model_copy(update={"reply_to": "Should I apply to remote DevOps jobs this week?"})
    store.write_card(c)
    index.rebuild(store)
    hits = index.search("remote devops jobs")
    assert hits and hits[0].card_id == "tg_r" and "remote DevOps" in hits[0].snippet
