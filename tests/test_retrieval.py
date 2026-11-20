import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from secondbrain import advisor
from secondbrain.advisor import PACK_CHARS, PROFILE_PACK_CHARS, build_context, build_prompt
from secondbrain.embed import HashEmbedder
from secondbrain.index import Hit, Index
from secondbrain.retrieval import (EVIDENCE_RULE, Evidence, coverage_line, format_evidence, make_expander, retrieve, rrf)
from secondbrain.schema import Card, KeyPoint, Topic
from secondbrain.store import Store

NOW = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)


def hit(cid, text, score, source="telegram", date="2026-11-10"):
    return Hit(card_id=cid, title=text[:30], snippet=text, score=score, date=date, source=source)


class FakeIndex:
    """search() returns canned hits per query and records every call."""

    def __init__(self, by_query, default=()):
        self.by_query, self.default, self.calls = by_query, list(default), []

    def search(self, query, **kw):
        self.calls.append((query, kw))
        return list(self.by_query.get(query, self.default))


# --- retrieve --------------------------------------------------------------------------------------------------

def test_strong_match_does_not_call_expand():
    index = FakeIndex({"q": [hit("a", "alpha text", 0.9), hit("b", "beta text", 0.6)]})
    calls = []
    result = retrieve(index, "q", k=5, expand=lambda q: calls.append(q) or ["other"])
    assert calls == [] and not result.weak and [e.card_id for e in result.items] == ["a", "b"]


def test_weak_match_calls_expand_once_and_fuses_the_rankings():
    index = FakeIndex({"q": [hit("a", "weak alpha", 0.2)],
                       "rephrased one": [hit("c", "the real answer", 0.8), hit("a", "weak alpha", 0.5)],
                       "rephrased two": [hit("c", "the real answer", 0.7)]})
    calls = []
    result = retrieve(index, "q", k=5, expand=lambda q: calls.append(q) or ["rephrased one", "rephrased two"])
    assert calls == ["q"] and result.weak and result.expansions == ["rephrased one", "rephrased two"]
    assert [e.card_id for e in result.items][0] == "c"            # found by two phrasings: ranked first
    assert {e.card_id for e in result.items} == {"a", "c"}        # same card + same text appears once


def test_expand_failure_or_empty_result_falls_back_to_the_plain_results():
    index = FakeIndex({"q": [hit("a", "weak alpha", 0.2)]})

    def boom(q):
        raise RuntimeError("model down")

    result = retrieve(index, "q", k=5, expand=boom)
    assert result.weak and [e.card_id for e in result.items] == ["a"] and result.expansions == []
    assert retrieve(FakeIndex({}), "q", k=5, expand=lambda q: ["x"]).items == []


def test_retrieve_asks_for_pack_sources_only_and_never_local_only_and_excludes_ids():
    index = FakeIndex({"q": [hit("a", "alpha", 0.9), hit("skip", "skipped", 0.8)]})
    result = retrieve(index, "q", k=5, exclude=frozenset({"skip"}), sources=frozenset({"telegram"}))
    assert [e.card_id for e in result.items] == ["a"]
    _, kw = index.calls[0]
    assert kw["include_local_only"] is False and kw["sources"] == frozenset({"telegram"})


def test_rrf_orders_by_combined_rank():
    assert rrf([["a", "b", "c"], ["c", "b"], ["c"]])[0] == "c"
    assert rrf([]) == []


def test_make_expander_returns_at_most_three_and_swallows_failures():
    class Llm:
        name, is_local = "fake", True

        def __init__(self, reply):
            self.reply = reply

        def complete(self, prompt, *, system=None):
            if isinstance(self.reply, Exception):
                raise self.reply
            return self.reply

    assert make_expander(Llm(json.dumps({"queries": ["a", "b", "c", "d"]})))("q") == ["a", "b", "c"]
    assert make_expander(Llm("not json"))("q") == []
    assert make_expander(Llm(RuntimeError("down")))("q") == []


# --- evidence text ------------------------------------------------------------------------------------------------

def test_coverage_line_format_and_empty_case():
    items = [Evidence("tg_1", "2026-10-03", "telegram", "a", 0.9), Evidence("tg_1", "2026-10-03", "telegram", "b", 0.8),
             Evidence("tg_2", "2026-11-18", "telegram", "c", 0.7), Evidence("adv_1", "2026-11-01", "advice", "d", 0.6)]
    assert coverage_line(items) == "Evidence: 3 notes from 2026-10-03 to 2026-11-18 (journal 2, advice 1)."
    assert coverage_line([]) == "Evidence: none found."


def test_format_evidence_shows_date_source_id_and_text():
    line = format_evidence([Evidence("tg_12", "2026-11-18", "telegram", "I want to build a tracker", 0.9)])[0]
    assert line == "[2026-11-18 journal tg_12] I want to build a tracker"


# --- the pack -------------------------------------------------------------------------------------------------------

def card(cid, text, source="telegram", days_ago=40, channel=None):
    return Card(id=cid, source=source, type="thought", title=text[:60], consumed_at=NOW - timedelta(days=days_ago),
                topic=Topic(primary="uncertain"), channel=channel,
                key_points=[KeyPoint(text=text, topic="uncertain", confidence=1.0)])


@pytest.fixture
def heavy(tmp_path: Path):
    """A library where everything else in the pack is as long as it can be."""
    store = Store(tmp_path / "brain")
    store.write_card(card("tg_old", "I never ask recruiters for anything because rejection feels like proof that I am not good enough"))
    for i in range(12):
        store.write_card(card(f"tg_recent{i}", f"recent entry {i} " + "filler words about my day " * 40, days_ago=i))
    for i in range(4):
        store.write_card(card(f"adv_{i}", "advice answer " + "long advice words " * 80, source="advice", days_ago=i + 1))
    index = Index(tmp_path / "i.db", HashEmbedder())
    index.rebuild(store)
    return store, index


def test_matched_evidence_survives_when_goals_profile_recent_and_advice_are_all_long(heavy):
    store, index = heavy
    pack = build_context(store, "why do I never ask recruiters for anything", "goal words " * 400, NOW, index=index,
                         profile="profile words " * 600)
    assert "recruiters" in pack and "[2026-" in pack and "tg_old" in pack      # the old note reaches the pack
    assert len(pack) <= PACK_CHARS


def test_pack_stays_under_the_budget_in_the_worst_case(heavy):
    store, index = heavy
    pack = build_context(store, "recent entry filler advice", "g" * 9000, NOW, index=index, profile="p" * 9000)
    assert len(pack) <= PACK_CHARS and "Evidence:" in pack


def test_profile_is_included_up_to_its_budget(heavy):
    store, index = heavy
    profile = "A" * 2400 + "ENDMARK"
    assert "ENDMARK" in build_context(store, "recruiters", "goals", NOW, index=index, profile=profile)
    cut = build_context(store, "recruiters", "goals", NOW, index=index, profile="B" * 6000 + "ENDMARK")
    assert "ENDMARK" not in cut and "B" * PROFILE_PACK_CHARS in cut and "B" * (PROFILE_PACK_CHARS + 1) not in cut


def test_pack_without_an_index_falls_back_to_keywords(heavy):
    store, _ = heavy
    pack = build_context(store, "recruiters rejection", "goals", NOW, index=None)
    assert "recruiters" in pack


def test_pack_never_contains_local_only_notes_and_a_broken_index_does_not_break_it(heavy):
    store, index = heavy
    store.write_card(card("tg_secret", "secret fear about recruiters and rejection", channel="local-only"))
    index.update(store)
    assert "secret fear" not in build_context(store, "recruiters rejection fear", "goals", NOW, index=index)

    class Broken:
        def search(self, *a, **k):
            raise RuntimeError("no model")

    assert "recruiters" in build_context(store, "recruiters rejection", "goals", NOW, index=Broken())


def test_expander_runs_only_for_weak_questions_inside_the_pack(heavy):
    store, index = heavy
    calls = []
    build_context(store, "why do I never ask recruiters for anything", "g", NOW, index=index, expand=lambda q: calls.append(q) or [])
    strong = len(calls)
    build_context(store, "zzzz qqqq xxxx", "g", NOW, index=index, expand=lambda q: calls.append(q) or [])
    assert strong == 0 and len(calls) == 1


def test_prompt_carries_the_evidence_rule():
    prompt = build_prompt("a question", "MEMORY BLOCK")
    assert EVIDENCE_RULE in prompt and "does not cover" in EVIDENCE_RULE


# --- the bot indexes a note the moment it is saved --------------------------------------------------------------------

def _save_in_one_loop(ctx, text, message_id):
    import asyncio

    from test_bot_app import make_update
    from secondbrain.bot.app import _save_capture

    async def scenario():
        u = make_update(text=text, message_id=message_id)
        await _save_capture(u, ctx.bot_data, text)
        await asyncio.gather(*ctx.bot_data.get("tasks", ()))  # the background indexing task
        return u

    return asyncio.run(scenario())


def test_a_saved_note_is_searchable_immediately_without_a_sync(tmp_path: Path):
    from test_bot_app import make_ctx
    store = Store(tmp_path / "brain")
    index = Index(tmp_path / "i.db", HashEmbedder())
    index.rebuild(store)  # an (empty) schema-2 index exists, as after the first sync
    ctx = make_ctx(store)
    ctx.bot_data["index"] = index
    _save_in_one_loop(ctx, "note about negotiating my first salary offer", 700)
    assert index.search("negotiating salary offer")[0].card_id == "tg_700"


def test_quiet_thought_saves_are_indexed_too_and_a_failing_index_never_breaks_saving(tmp_path: Path):
    from test_bot_app import make_ctx
    store = Store(tmp_path / "brain")
    ctx = make_ctx(store)

    class BrokenIndex:
        def add_card(self, card):
            raise RuntimeError("embedding model down")

    ctx.bot_data["index"] = BrokenIndex()
    u = _save_in_one_loop(ctx, "thought: remember to email the recruiter tomorrow morning", 701)
    assert store.has("tg_701") and u.message.replies[0][0].startswith("Saved")   # saved and confirmed despite the failure
