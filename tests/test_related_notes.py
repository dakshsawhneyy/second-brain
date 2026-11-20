"""'You have written about this before' must be useful, quiet when unsure, and never echo the bot's own questions."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from secondbrain.bot.app import _suggest_related
from secondbrain.chunks import Chunk, chunk_card
from secondbrain.index import Hit, Index
from secondbrain.schema import Card, KeyPoint, Topic
from secondbrain.embed import HashEmbedder
from secondbrain.store import Store

from test_bot_app import NOW, FakeMessage, make_ctx, make_update, run
from test_bot_app import store  # noqa: F401  (fixture)

WHEN = datetime(2026, 11, 17, 10, 0, tzinfo=timezone.utc)


def note(cid, texts, source="telegram", when=WHEN, **extra):
    return Card(id=cid, source=source, type="thought", title=texts[0][:60], consumed_at=when,
                topic=Topic(primary="uncertain"), key_points=[KeyPoint(text=t, topic="uncertain", confidence=1.0) for t in texts],
                **extra)


# --- chunking: a question/answer card is searchable by the question but shows only the answer ------------------------

def test_question_answer_pair_is_one_chunk_with_the_question_as_embedding_context():
    card = note("mo_1", ["Q: What is the one thing you keep avoiding?", "A: Cold outreach to recruiters."], source="mentor")
    assert chunk_card(card) == [Chunk(id="mo_1#0", card_id="mo_1", ord=0, text="Cold outreach to recruiters.",
                                      context="What is the one thing you keep avoiding?")]


def test_a_lone_q_line_without_an_answer_is_kept_as_it_is():
    card = note("x_1", ["Q: Is this a question without an answer?"])
    assert [c.text for c in chunk_card(card)] == ["Q: Is this a question without an answer?"]


# --- index: match on the question, show the answer; filter by day and source -------------------------------------

def test_answer_card_is_found_by_the_question_words_but_its_snippet_is_the_answer(tmp_path: Path):
    store = Store(tmp_path)
    store.write_card(note("mo_1", ["Q: Which pressure comes from your family at home?", "A: Mostly money, they expect a job soon."],
                          source="mentor"))
    index = Index(tmp_path / "i.db", HashEmbedder())
    index.rebuild(store)
    hit = index.search("pressure family home")[0]
    assert hit.card_id == "mo_1" and hit.snippet == "Mostly money, they expect a job soon."


def test_related_can_be_limited_to_earlier_days_and_chosen_sources(tmp_path: Path):
    store = Store(tmp_path)
    old = WHEN - timedelta(days=5)
    store.write_card(note("tg_old", ["worried about money and the first job"], when=old))
    store.write_card(note("tg_today", ["worried about money and the first job today"], when=WHEN))
    store.write_card(note("adv_1", ["worried about money and the first job answer"], source="advice", when=old))
    index = Index(tmp_path / "i.db", HashEmbedder())
    index.rebuild(store)
    everything = {h.card_id for h in index.related("worried about money and the first job", k=5, min_cosine=0.1)}
    assert everything == {"tg_old", "tg_today", "adv_1"}
    cutoff = WHEN.astimezone().date().isoformat()
    earlier = index.related("worried about money and the first job", k=5, min_cosine=0.1, before=cutoff,
                            sources=frozenset({"telegram"}))
    assert [h.card_id for h in earlier] == ["tg_old"]


# --- the bot: when to speak, and what to say ---------------------------------------------------------------------

class FakeIndex:
    def __init__(self, hits):
        self.hits, self.calls = hits, []

    def related(self, text, k=3, min_cosine=0.55, exclude=frozenset(), **kw):
        self.calls.append({"text": text, "min_cosine": min_cosine, "exclude": exclude, **kw})
        return self.hits


def saved_card(text, reply_to=None, cid="tg_900"):
    return Card(id=cid, source="telegram", type="thought", title=text[:60], consumed_at=NOW, reply_to=reply_to,
                topic=Topic(primary="uncertain"), key_points=[KeyPoint(text=text, topic="uncertain", confidence=1.0)])


def ask_related(store, hits, card):
    ctx = make_ctx(store)
    ctx.bot_data["index"] = FakeIndex(hits)
    u = make_update(text=card.key_points[0].text, message_id=900)
    run(_suggest_related(u, ctx.bot_data, card))
    return u, ctx.bot_data["index"]


def test_answering_a_question_never_triggers_suggestions(store):
    card = saved_card("I think the answer is that I avoid cold outreach", reply_to="What do you keep avoiding?")
    u, index = ask_related(store, [Hit("old", "t", "something old", 0.9, "2026-11-10", "telegram")], card)
    assert u.message.replies == [] and index.calls == []


def test_lookup_only_sees_earlier_days_and_his_own_writing_with_a_strict_threshold(store):
    card = saved_card("I keep thinking about building a habit tracker for interview prep")
    _, index = ask_related(store, [], card)
    call = index.calls[0]
    assert call["before"] == NOW.astimezone().date().isoformat()          # nothing from today
    assert call["sources"] == frozenset({"telegram", "mentor", "claude-chat"})  # never Claude's advice
    assert call["min_cosine"] >= 0.7                                       # similar in meaning, not just in topic


def test_suggestion_shows_date_and_text_once_without_the_title_and_skips_echoes_of_the_new_note(store):
    card = saved_card("I keep thinking about building a habit tracker for interview prep")
    hits = [Hit("tg_a", "Late at night I read about habit loops", "Late at night I read about habit loops and decided to build a tracker.", 0.8, "2026-11-12", "telegram"),
            Hit("tg_echo", "dup", "I keep thinking about building a habit tracker for interview prep", 0.99, "2026-11-13", "telegram")]
    u, _ = ask_related(store, hits, card)
    text = u.message.replies[0][0]
    assert text.count("Late at night I read about habit loops") == 1          # not "title: title"
    assert "12 Nov" in text and "echo" not in text and "I keep thinking about building" not in text
    assert "tg_a" not in text and "tg_echo" not in text                       # no internal ids shown


def test_when_every_hit_is_an_echo_or_empty_nothing_is_sent(store):
    card = saved_card("I keep thinking about building a habit tracker for interview prep")
    u, _ = ask_related(store, [Hit("tg_echo", "dup", "I keep thinking about building a habit tracker for interview prep", 0.99, "2026-11-13", "telegram")], card)
    assert u.message.replies == []


def test_identical_text_from_two_cards_is_shown_only_once(store):
    card = saved_card("I keep thinking about building a habit tracker for interview prep")
    twin = "Late at night I read about habit loops and decided to build a tracker."
    hits = [Hit("mo_32", "t", twin, 0.8, "2026-11-12", "mentor"), Hit("tg_32", "t", twin, 0.8, "2026-11-12", "telegram")]
    u, _ = ask_related(store, hits, card)
    assert u.message.replies[0][0].count("Late at night") == 1
