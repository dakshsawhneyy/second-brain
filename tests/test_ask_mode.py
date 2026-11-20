"""/ask is Vikram in a fuller mode: a real answer from an operator's point of view, human, no note ids."""

from datetime import datetime, timedelta, timezone

import pytest

from secondbrain.mentor.guards import strip_note_ids
from secondbrain.mentor.persona import ASK_MODE, PERSONA
from secondbrain.store import Store

from test_mentor import FakeClaude, make_mentor

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 11, 20, 12, 0, tzinfo=IST)


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "brain")


# --- ids never reach him ---------------------------------------------------------------------------------------

def test_strip_note_ids_removes_bracketed_and_bare_ids_and_keeps_normal_text():
    assert strip_note_ids("You dropped it [mo_32] and said so (tg_12).") == "You dropped it and said so."
    assert strip_note_ids("Per [mc_20261120_1], and [dgd_20261118] too.") == "Per, and too."
    text = "A note [see below] about cost_per_month and tg_notes stay."
    assert strip_note_ids(text) == text                                       # not real id shapes: untouched
    assert strip_note_ids("No ids here.") == "No ids here."


def test_ask_answers_reach_him_without_note_ids_and_are_saved_without_them(store, tmp_path):
    claude = FakeClaude(replies=["You told me you dropped it [mo_32] and never tried to sell [mo_40]. Start with one person."])
    m = make_mentor(store, tmp_path, claude)
    answer = m.ask("what should I do first?", NOW, 701)
    assert "[mo_" not in answer and "mo_32" not in answer and answer.startswith("You told me you dropped it")
    saved = " ".join(k.text for c in store.iter_cards() if c.source == "advice" for k in c.key_points)
    assert "mo_32" not in saved


# --- the mode itself -----------------------------------------------------------------------------------------------

def test_ask_uses_vikram_plus_the_ask_mode_instructions(store, tmp_path):
    claude = FakeClaude()
    m = make_mentor(store, tmp_path, claude)
    m.ask("how do I find my first customer?", NOW, 702)
    system = claude.calls[-1][0]
    assert system.startswith(PERSONA) and ASK_MODE in system


def test_ask_mode_overrides_the_check_in_style_and_forbids_ids_lists_and_filler():
    low = " ".join(ASK_MODE.lower().split())
    assert "150 to 250 words" in low and "overrides" in low                    # a real answer, not a 40-word text
    assert "do not write note ids" in low and "no lists" in low and "no headings" in low
    assert "generic" in low and "read a book" in low                           # no checklist filler
    assert "steelman" in low or "synthesis" in low                             # respects his reasoning


def test_ask_mode_carries_the_operator_lens_without_inventing_stories_or_facts():
    low = " ".join(ASK_MODE.lower().split())
    for idea in ("specific person", "by hand", "distribution", "charge", "weekly", "unfair", "one bet"):
        assert idea in low, idea
    assert "never invent" in low and "stories" in low                          # only the checkable STORIES may be told
    assert "guarantee" in low or "promise" in low                              # no promises of wealth


def test_ask_mode_keeps_every_safety_rule_of_the_persona():
    # the addendum must not weaken the character: it only changes length, shape and thinking
    assert "TRUTH OVER COMFORT" in PERSONA and "CONCERNED" in PERSONA
    assert "safety" in ASK_MODE.lower() or "concerned" in ASK_MODE.lower()


def test_daily_messages_are_unchanged_short_check_ins(store, tmp_path):
    claude = FakeClaude()
    m = make_mentor(store, tmp_path, claude)
    m.start_onboarding(NOW)                                                   # a structured daily-style message
    assert ASK_MODE not in claude.calls[-1][0]


# --- Claude's own earlier answers are not facts about him -------------------------------------------------------------

def _advice_card(cid, text, days_ago=1):
    from secondbrain.schema import Card, KeyPoint, Topic
    return Card(id=cid, source="advice", type="thought", title="q", consumed_at=NOW - timedelta(days=days_ago),
                topic=Topic(primary="uncertain"),
                key_points=[KeyPoint(text="Q: what now?", topic="uncertain", confidence=1.0),
                            KeyPoint(text=text, topic="uncertain", confidence=1.0)])


def test_earlier_answers_are_labelled_as_what_was_said_before_not_facts_about_him(store):
    from secondbrain.advisor import build_context
    store.write_card(_advice_card("adv_1", "A: People paid you about Rs 3.4 lakh to teach this year."))
    pack = build_context(store, "what should I do", "goals", NOW)
    header = next(line for line in pack.splitlines() if line.startswith("THE CONVERSATION SO FAR"))
    assert "not facts about him" in header.lower()


def test_old_advice_answers_never_come_back_as_search_evidence(store, tmp_path):
    from secondbrain.advisor import build_context
    from secondbrain.embed import HashEmbedder
    from secondbrain.index import Index
    store.write_card(_advice_card("adv_1", "A: People paid you about Rs 3.4 lakh to teach cloud this year.", days_ago=40))
    store.write_card(_advice_card("adv_2", "A: Send ten messages tomorrow morning.", days_ago=2))   # the two newest answers
    store.write_card(_advice_card("adv_3", "A: Review the replies on Friday evening.", days_ago=1))  # fill the "earlier" slots
    index = Index(tmp_path / "i.db", HashEmbedder())
    index.rebuild(store)
    pack = build_context(store, "how much did people pay me to teach cloud", "goals", NOW, index=index)
    evidence = pack.split("EVIDENCE FROM HIS NOTES")[1]
    assert "3.4 lakh" not in evidence


def test_ask_mode_limits_numbers_to_what_he_wrote_himself():
    low = " ".join(ASK_MODE.lower().split())
    assert "only figures he wrote himself" in low and "earlier conversation" in low and "not a fact about him" in low
