from datetime import datetime, timedelta, timezone

from secondbrain.bot.brief import build_morning_brief
from secondbrain.schema import Action, Card, Relevance, Topic
from secondbrain.store import Store

NOW = datetime(2026, 11, 19, 8, 0, tzinfo=timezone.utc)


def _card(cid, source, action, hours_ago=2, score=None):
    rel = Relevance(bet_job=5, bet_product=5, actionability=5, novelty=5, quality=5, score=score) if score is not None else None
    return Card(id=cid, source=source, type="acted", title=cid, consumed_at=NOW - timedelta(hours=hours_ago),
                topic=Topic(primary="uncertain"), action=Action(text=action), relevance=rel)


def test_unscored_session_and_chat_actions_never_become_todays_action(tmp_path):
    store = Store(tmp_path)
    store.write_card(_card("cc_1", "claude-code", "Review 18 older clips"))
    store.write_card(_card("ch_1", "claude-chat", "Think about pricing"))
    brief = build_morning_brief(store, "", NOW)
    assert brief.action_id is None and "Review 18" not in brief.text and "pricing" not in brief.text


def test_his_own_telegram_actions_still_count(tmp_path):
    store = Store(tmp_path)
    store.write_card(_card("tg_1", "telegram", "Send 5 applications"))
    store.write_card(_card("cc_1", "claude-code", "Review 18 older clips"))
    brief = build_morning_brief(store, "", NOW)
    assert brief.action_id == "tg_1"


def test_scored_cards_from_any_source_still_qualify(tmp_path):
    store = Store(tmp_path)
    store.write_card(_card("yt_1", "youtube", "Try the k8s lab", score=80))
    assert build_morning_brief(store, "", NOW).action_id == "yt_1"


def _own(cid, text, days_ago=0, type_="thought", hours=2):
    c = _card(cid, "telegram", text, hours_ago=days_ago * 24 + hours)
    return c.model_copy(update={"type": type_})


def test_own_items_rank_first_and_show_their_age(tmp_path):
    store = Store(tmp_path)
    store.write_card(_card("yt_1", "youtube", "Try the k8s lab", score=90))
    store.write_card(_own("tg_old", "Send 5 applications", days_ago=12))
    text = build_morning_brief(store, "", NOW).text
    assert text.index("Send 5 applications") < text.index("Try the k8s lab")
    assert "Send 5 applications (open 12 days)" in text


def test_yesterday_block_lists_done_and_worked_on(tmp_path):
    store = Store(tmp_path)
    store.write_card(_own("tg_d", "x", days_ago=1, type_="produced").model_copy(update={"title": "shipped the brief"}))
    sess = _card("cc_1", "claude-code", "Wire the scheduler", hours_ago=26).model_copy(
        update={"channel": "z second brain", "title": "Built the importer"})
    store.write_card(sess)
    text = build_morning_brief(store, "", NOW).text
    assert "Done: shipped the brief" in text and "Worked on: Built the importer" in text
    assert "Nothing shipped was logged" not in text


def test_focus_project_leftover_is_suggested_but_other_projects_are_not(tmp_path):
    store = Store(tmp_path)
    store.write_card(_card("cc_a", "claude-code", "Schedule the sync task").model_copy(update={"channel": "z second brain"}))
    store.write_card(_card("cc_b", "claude-code", "Re-render 18 clips", hours_ago=1).model_copy(update={"channel": "yt-shorts"}))
    text = build_morning_brief(store, "", NOW).text
    assert "Schedule the sync task" in text and "Re-render" not in text


def test_focus_projects_can_be_overridden(tmp_path):
    store = Store(tmp_path)
    store.write_card(_card("cc_b", "claude-code", "Re-render 18 clips").model_copy(update={"channel": "yt-shorts"}))
    assert "Re-render" in build_morning_brief(store, "", NOW, focus_projects=("yt-shorts",)).text


def test_at_most_three_suggestions(tmp_path):
    store = Store(tmp_path)
    for i in range(6):
        store.write_card(_own(f"tg_{i}", f"task {i}", hours=i + 1))
    text = build_morning_brief(store, "", NOW).text
    assert sum(f"task {i}" in text for i in range(6)) == 3


def test_nothing_shipped_nudge_when_yesterday_is_empty(tmp_path):
    assert "Nothing shipped was logged yesterday" in build_morning_brief(Store(tmp_path), "", NOW).text
