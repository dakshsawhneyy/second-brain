import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from secondbrain.bot.app import on_text
from secondbrain.bot.classify import classify_text
from secondbrain.store import Store

OWNER = 1434918489
NOW = datetime(2026, 11, 18, 10, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))


class _Msg:
    def __init__(self, text, mid):
        self.text, self.message_id, self.date, self.replies = text, mid, None, []

    async def reply_text(self, text, **kw):
        self.replies.append(text)


def _update(text, mid):
    return SimpleNamespace(effective_user=SimpleNamespace(id=OWNER),
                           effective_chat=SimpleNamespace(id=OWNER, type="private"), message=_Msg(text, mid),
                           callback_query=None)


def _ctx(store, classifier):
    return SimpleNamespace(bot_data={"store": store, "goals_text": "", "owner_id": OWNER,
                                     "now": lambda: NOW, "classifier": classifier})


async def _send(ctx, text, mid):
    u = _update(text, mid)
    await on_text(u, ctx)
    await asyncio.gather(*list(ctx.bot_data.get("tasks", ())))
    return u


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "brain")


def test_untagged_message_is_labelled_in_the_background(store):
    ctx = _ctx(store, lambda text: ("book", "growth/mindset"))
    u = asyncio.run(_send(ctx, "Read chapter 3 today: monopolies matter more than competition, pick a niche", 300))
    assert u.message.replies == ["Saved: thought"]  # instant reply, unchanged
    card = store.read_card("tg_300")
    assert card.type == "book" and card.topic.primary == "growth/mindset"


def test_tagged_and_short_messages_are_not_relabelled(store):
    ctx = _ctx(store, lambda text: ("book", "growth/mindset"))
    asyncio.run(_send(ctx, "idea: a longer idea about something I want to try soon", 301))
    asyncio.run(_send(ctx, "short", 302))
    assert store.read_card("tg_301").type == "thought" and store.read_card("tg_302").type == "thought"


def test_classifier_failure_keeps_the_saved_thought(store):
    def broken(text):
        raise RuntimeError("model offline")

    asyncio.run(_send(_ctx(store, broken), "a long enough message about how I feel today", 310))
    assert store.read_card("tg_310").type == "thought"


class _Fake:
    name, is_local = "fake", True

    def __init__(self, out):
        self.out = out

    def complete(self, prompt, *, system=None):
        return self.out


def test_classify_maps_kinds_and_never_returns_shipped():
    assert classify_text("x" * 30, _Fake('{"kind": "decision", "topic": "career/strategy"}')) == ("decided", "career/strategy")
    assert classify_text("x" * 30, _Fake('{"kind": "shipped", "topic": "nonsense"}')) == ("thought", "uncertain")


def test_a_decision_is_never_reported_as_done_in_the_brief(store):
    from secondbrain.bot.brief import build_morning_brief
    from secondbrain.schema import Card, Topic
    now = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)
    store.write_card(Card(id="tg_1", source="telegram", type="decided", title="I decided to rest all week",
                          consumed_at=now - timedelta(hours=14), topic=Topic(primary="uncertain")))
    assert "Done:" not in build_morning_brief(store, "", now).text


def test_brief_numbering_survives_a_restart(store, tmp_path):
    from secondbrain.bot.app import _mark_command, _remember_ids
    from secondbrain.schema import Action, Card, Topic
    for i, t in enumerate(("A task", "B task", "C task")):
        store.write_card(Card(id=f"tg_{10 + i}", source="telegram", type="thought", title=t,
                              consumed_at=NOW - timedelta(hours=i + 1), topic=Topic(primary="uncertain"),
                              action=Action(text=t)))
    state = tmp_path / "bot_state.json"
    first = SimpleNamespace(bot_data={"store": store, "goals_text": "", "owner_id": OWNER, "now": lambda: NOW,
                                      "state_path": state}, args=["2"])
    _remember_ids(first.bot_data, ["tg_10", "tg_11", "tg_12"])
    asyncio.run(_mark_command("skip")(_update("/skip 2", 400), first))
    # the bot restarts: memory is gone, the file remains; "/skip 2" must hit the same numbering, not the shifted one
    second = SimpleNamespace(bot_data={"store": store, "goals_text": "", "owner_id": OWNER, "now": lambda: NOW,
                                       "state_path": state}, args=["3"])
    asyncio.run(_mark_command("skip")(_update("/skip 3", 401), second))
    assert store.read_card("tg_11").action.status == "skipped" and store.read_card("tg_12").action.status == "skipped"
    assert store.read_card("tg_10").action.status == "open"
