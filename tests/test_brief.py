from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from secondbrain.bot.brief import FALLBACK_ACTION, Brief, apply_feedback, build_evening_checkin, build_morning_brief
from secondbrain.schema import Action, Card, KeyPoint, Relevance
from secondbrain.store import Store

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 11, 18, 9, 0, tzinfo=IST)
YESTERDAY = NOW - timedelta(days=1)
GOALS = "PRIVATE-GOALS: land a remote infra role, sell a product."


def make(id, title="A video", when=YESTERDAY, score=60, topic="infra/sre", type_="consumed", action=None, tier="hot") -> Card:
    return Card(
        id=id, source="youtube", type=type_, title=title, consumed_at=when,
        topic={"primary": topic, "secondary": []}, tier=tier,
        relevance=Relevance(bet_job=5, bet_product=5, actionability=5, novelty=5, quality=5, score=score),
        key_points=[KeyPoint(text="SECRET-DETAIL", topic=topic, t=None, confidence=0.9)],
        action=Action(text=action) if action else None,
    )


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "brain")


def test_morning_brief_has_exactly_one_action(store):
    store.write_card(make("yt_a", action="Try Terraform modules"))
    store.write_card(make("yt_b", action="Write a runbook", score=40))
    b = build_morning_brief(store, GOALS, NOW)
    assert b.text.count("Today's one action") == 1
    assert "Try Terraform modules" in b.text and b.action_id == "yt_a"
    # the runner-up is shown as a plain list item (no buttons), after the single primary action
    assert b.text.index("Try Terraform modules") < b.text.index("Also on your list") < b.text.index("Write a runbook")


def test_brief_without_cards_uses_fallback_action_and_no_buttons(store):
    b = build_morning_brief(store, GOALS, NOW)
    assert FALLBACK_ACTION in b.text and b.action_id is None and b.buttons == []
    assert "nothing" in b.text.lower()


def test_buttons_carry_card_id(store):
    store.write_card(make("yt_a", action="Do it"))
    b = build_morning_brief(store, GOALS, NOW)
    assert b.buttons == [("Done", "done:yt_a"), ("Later", "later:yt_a"), ("Skip", "skip:yt_a")]
    assert all(len(cb.encode()) <= 64 for _, cb in b.buttons)


def test_overlong_callback_data_drops_buttons_but_keeps_action(store):
    long_id = "x" * 70
    store.write_card(make(long_id, action="Do it"))
    b = build_morning_brief(store, GOALS, NOW)
    assert "Do it" in b.text and b.buttons == []


def test_brief_lists_at_most_three_yesterday_items_best_first(store):
    for i, score in enumerate([30, 90, 50, 70, 60]):
        store.write_card(make(f"yt_{i}", title=f"Title {i}", score=score))
    text = build_morning_brief(store, GOALS, NOW).text
    shown = [f"Title {i}" for i in (1, 3, 4)]  # scores 90, 70, 60
    assert all(t in text for t in shown)
    assert "Title 0" not in text and "Title 2" not in text
    assert text.index("Title 1") < text.index("Title 3") < text.index("Title 4")


def test_brief_excludes_noise_other_days_and_non_consumed_types(store):
    store.write_card(make("yt_noise", title="Gameplay", topic="noise/entertainment"))
    store.write_card(make("yt_old", title="Old video", when=YESTERDAY - timedelta(days=3)))
    store.write_card(make("tg_note", title="My own note", type_="thought"))
    store.write_card(make("yt_cold", title="Cold one", tier="cold"))
    store.write_card(make("yt_ok", title="Good one"))
    text = build_morning_brief(store, GOALS, NOW).text
    assert "Good one" in text
    for hidden in ("Gameplay", "Old video", "My own note", "Cold one"):
        assert hidden not in text


def test_yesterday_uses_the_clock_of_now_not_utc(store):
    # 20:00 UTC on 16 Nov is 01:30 IST on 17 Nov, which is "yesterday" for a brief at 09:00 IST on 18 Nov.
    store.write_card(make("yt_tz", title="Late night video", when=datetime(2026, 11, 16, 20, 0, tzinfo=timezone.utc)))
    assert "Late night video" in build_morning_brief(store, GOALS, NOW).text


def test_action_comes_from_best_recent_open_action_and_skips_finished_ones(store):
    store.write_card(make("yt_done", score=95, action="Already done").model_copy(update={"action": Action(text="Already done", status="done")}))
    store.write_card(make("yt_skip", score=90, action="Skipped one").model_copy(update={"action": Action(text="Skipped one", status="skipped")}))
    store.write_card(make("yt_open", score=50, action="Open one"))
    b = build_morning_brief(store, GOALS, NOW)
    assert b.action_id == "yt_open" and "Open one" in b.text


def test_later_actions_are_eligible_again(store):
    store.write_card(make("yt_later", action="Revisit me").model_copy(update={"action": Action(text="Revisit me", status="later")}))
    assert build_morning_brief(store, GOALS, NOW).action_id == "yt_later"


def test_old_actions_beyond_a_week_are_not_offered(store):
    store.write_card(make("yt_stale", when=NOW - timedelta(days=10), action="Stale"))
    b = build_morning_brief(store, GOALS, NOW)
    assert b.action_id is None and FALLBACK_ACTION in b.text


def test_brief_never_shows_key_point_text_or_unmarked_goals(store):
    store.write_card(make("yt_a", title="Visible title", action="Do it"))
    text = build_morning_brief(store, GOALS, NOW).text
    assert "SECRET-DETAIL" not in text and "PRIVATE-GOALS" not in text


def test_focus_line_in_goals_is_shown(store):
    goals = "# Goals\nFocus: ship one thing daily\nPRIVATE: details"
    text = build_morning_brief(store, goals, NOW).text
    assert "ship one thing daily" in text and "PRIVATE: details" not in text


def test_brief_text_fits_telegram_limit_even_with_extreme_content(store):
    for i in range(100):
        store.write_card(make(f"yt_{i}", title="T" * 500, action="A" * 2000))
    assert len(build_morning_brief(store, "Focus: " + "f" * 5000, NOW).text) <= 4096


def test_evening_checkin_asks_and_has_no_buttons():
    b = build_evening_checkin(NOW)
    assert isinstance(b, Brief) and b.buttons == [] and b.action_id is None
    assert "produce" in b.text.lower() and "book" in b.text and "shipped" in b.text


def test_apply_feedback_done_later_skip(store):
    store.write_card(make("yt_a", action="Do it"))
    apply_feedback(store, "done:yt_a")
    c = store.read_card("yt_a")
    assert c.action.status == "done" and c.user.acted is True
    apply_feedback(store, "later:yt_a")
    assert store.read_card("yt_a").action.status == "later"
    apply_feedback(store, "skip:yt_a")
    c = store.read_card("yt_a")
    assert c.action.status == "skipped" and c.user.acted is False


@pytest.mark.parametrize("data", ["done:yt_missing", "bogus", "", "done:", ":yt_a", "explode:yt_a", "done:../../etc", "done:" + "x" * 500])
def test_apply_feedback_bad_input_is_a_noop(store, data):
    store.write_card(make("yt_a", action="Do it"))
    apply_feedback(store, data)
    assert store.read_card("yt_a").action.status == "open"


def test_apply_feedback_on_card_without_action_is_a_noop(store):
    store.write_card(make("yt_a"))
    apply_feedback(store, "done:yt_a")
    c = store.read_card("yt_a")
    assert c.action is None and c.user.acted is None
