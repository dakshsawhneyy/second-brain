from datetime import datetime, timedelta, timezone

import pytest

from secondbrain.advisor import (AdviceError, LOCAL_ONLY, ask, build_context, build_prompt, save_exchange)
from secondbrain.bot.capture import parse_capture
from secondbrain.store import Store

NOW = datetime(2026, 11, 19, 20, 0, tzinfo=timezone.utc)


def _entry(store, text, hours_ago=1, prefix="journal"):
    card = parse_capture(f"{prefix}: {text}", NOW - timedelta(hours=hours_ago), message_id=int(hours_ago * 100) + len(text))
    store.write_card(card)
    return card


def test_private_entries_are_stored_but_never_in_the_context_pack(tmp_path):
    store = Store(tmp_path)
    _entry(store, "I argued with my brother about money", 1, "journal")
    secret = _entry(store, "my private worry about health", 2, "private")
    assert secret.channel == LOCAL_ONLY and store.has(secret.id)
    pack = build_context(store, "what about my brother and health", "Focus: ship", NOW)
    assert "brother" in pack and "private worry" not in pack


def test_pack_redacts_secrets_and_is_bounded(tmp_path):
    store = Store(tmp_path)
    _entry(store, "note sk-abcdefghijklmnopqrstuvwxyz123456 " + "x" * 3000)
    pack = build_context(store, "note", "g" * 5000, NOW)
    assert "sk-abcdefghijklmnop" not in pack and len(pack) <= 7000


def test_ask_saves_the_exchange_and_feeds_it_back_next_time(tmp_path):
    store = Store(tmp_path)
    seen = []

    def runner(system, prompt):
        seen.append(prompt)
        return "Take the offer, then negotiate."

    ans = ask(store, "should I take the offer?", "Focus: ship", NOW, message_id=7, runner=runner)
    assert ans.startswith("Take the offer")
    card = store.read_card("adv_7")
    assert card.source == "advice" and card.key_points[0].text.startswith("Q: should I")
    ask(store, "and the salary?", "", NOW + timedelta(minutes=5), message_id=8, runner=runner)
    assert "Take the offer, then negotiate." in seen[1]


def test_failed_claude_still_keeps_the_question(tmp_path):
    store = Store(tmp_path)

    def broken(system, prompt):
        raise AdviceError("offline")

    with pytest.raises(AdviceError):
        ask(store, "what now?", "", NOW, message_id=9, runner=broken)
    assert store.read_card("adq_9").key_points[0].text == "what now?"
    assert not store.has("adv_9")


def test_empty_question_and_daily_limit(tmp_path):
    store = Store(tmp_path)
    with pytest.raises(AdviceError):
        ask(store, "  ", "", NOW, runner=lambda s, p: "x")
    save_exchange(store, "q1", "a1", NOW, 1)
    with pytest.raises(AdviceError, match="Daily limit"):
        ask(store, "q2", "", NOW, message_id=2, runner=lambda s, p: "x", daily_limit=1)


def test_prompt_marks_memory_as_data():
    assert "MEMORY" in build_prompt("hi", "ctx")


def test_the_default_daily_limit_is_twenty_questions(tmp_path):
    from secondbrain.advisor import DEFAULT_DAILY_LIMIT
    assert DEFAULT_DAILY_LIMIT == 20
    store = Store(tmp_path / "b")
    for i in range(19):
        ask(store, f"question {i}", "", NOW, message_id=i + 1, runner=lambda s, p: "answer")   # the 20th is still allowed
    ask(store, "question 19", "", NOW, message_id=20, runner=lambda s, p: "answer")
    with pytest.raises(AdviceError, match="Daily limit of 20"):
        ask(store, "one too many", "", NOW, message_id=21, runner=lambda s, p: "answer")
