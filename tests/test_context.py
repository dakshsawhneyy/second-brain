from datetime import datetime, timezone
from pathlib import Path

import pytest

from secondbrain.context import PROFILE_MAX_CHARS, build_context
from secondbrain.embed import HashEmbedder
from secondbrain.index import Index
from secondbrain.schema import Card, KeyPoint, Relevance
from secondbrain.store import Store

WHEN = datetime(2026, 11, 17, 10, 0, tzinfo=timezone.utc)


def card(i: int, title: str, point: str = "") -> Card:
    return Card(
        id=f"yt_{i:05d}", source="youtube", type="consumed", title=title, consumed_at=WHEN,
        topic={"primary": "infra/sre", "secondary": []},
        relevance=Relevance(bet_job=5, bet_product=5, actionability=5, novelty=5, quality=5, score=50),
        key_points=[KeyPoint(text=point, topic="infra/sre", t=None, confidence=0.8)] if point else [],
    )


def build_index(tmp_path: Path, cards: list[Card]) -> Index:
    store = Store(tmp_path / "brain")
    for c in cards:
        store.write_card(c)
    index = Index(tmp_path / "brain" / "index" / "brain.db", HashEmbedder())
    index.rebuild(store)
    return index


def write_profile(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "profile.md"
    p.write_text(text, encoding="utf-8")
    return p


def test_context_length_bounded_with_1000_cards(tmp_path: Path):
    cards = [card(i, f"kubernetes lesson {i}", "pods and services " * 5) for i in range(1000)]
    index = build_index(tmp_path, cards)
    profile = write_profile(tmp_path, "I want an infra job. " * 50)
    assert len(build_context("kubernetes pods", index, profile, max_chars=8000)) <= 8000
    assert len(build_context("kubernetes pods", index, profile, max_chars=500)) <= 500


def test_context_size_does_not_grow_with_corpus(tmp_path: Path):
    profile = write_profile(tmp_path, "Profile text.")
    small = build_index(tmp_path / "a", [card(i, f"devops note {i}", "point") for i in range(5)])
    big = build_index(tmp_path / "b", [card(i, f"devops note {i}", "point") for i in range(500)])
    a = build_context("devops", small, profile)
    b = build_context("devops", big, profile)
    assert len(b) <= 8000 and len(a) <= 8000
    assert len(b) < len(a) * 4  # bounded by the top-k cut, not by corpus size


def test_context_contains_profile_and_top_hit(tmp_path: Path):
    index = build_index(tmp_path, [card(1, "Kubernetes networking", "services route traffic"), card(2, "Pasta", "boil water")])
    profile = write_profile(tmp_path, "Daksh wants a remote infra role.")
    ctx = build_context("kubernetes", index, profile)
    assert "Daksh wants a remote infra role." in ctx
    assert "[yt_00001] Kubernetes networking: services route traffic" in ctx
    assert "yt_00002" not in ctx


def test_missing_profile_returns_hits_only(tmp_path: Path):
    index = build_index(tmp_path, [card(1, "Kubernetes networking", "services route traffic")])
    ctx = build_context("kubernetes", index, tmp_path / "nope.md")
    assert "About me" not in ctx and "yt_00001" in ctx


def test_profile_is_truncated(tmp_path: Path):
    index = build_index(tmp_path, [card(1, "Kubernetes", "x")])
    profile = write_profile(tmp_path, "p" * 10000)
    ctx = build_context("kubernetes", index, profile)
    assert "p" * PROFILE_MAX_CHARS in ctx and "p" * (PROFILE_MAX_CHARS + 1) not in ctx


def test_no_profile_and_no_hits_returns_empty_string(tmp_path: Path):
    index = build_index(tmp_path, [card(1, "Kubernetes", "x")])
    assert build_context("zzzunmatched", index, tmp_path / "nope.md") == ""


def test_newlines_in_snippets_are_flattened(tmp_path: Path):
    index = build_index(tmp_path, [card(1, "Kubernetes", "line one\nline two")])
    ctx = build_context("kubernetes", index, tmp_path / "nope.md")
    assert "line one line two" in ctx


@pytest.mark.parametrize("budget", [0, 1, 10, 50])
def test_tiny_budgets_never_exceeded(tmp_path: Path, budget):
    index = build_index(tmp_path, [card(1, "Kubernetes", "services")])
    profile = write_profile(tmp_path, "profile " * 20)
    assert len(build_context("kubernetes", index, profile, max_chars=budget)) <= budget

