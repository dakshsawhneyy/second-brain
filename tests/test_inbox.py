import asyncio
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from secondbrain.bot.app import (
    _capture_raw, _record_inbound, _replay_inbox, on_text, on_voice,
)
from secondbrain.inbox import MAX_TRIES, Inbox
from secondbrain.store import Store

from test_bot_app import FakeMessage, FakeTranscriber, OWNER, _voice_update, make_ctx, make_update, run


def test_inbox_survives_a_restart_and_is_idempotent(tmp_path: Path):
    path = tmp_path / "inbox.json"
    Inbox(path).add(5, {"kind": "text", "text": "hello"})
    again = Inbox(path)
    again.add(5, {"kind": "text", "text": "other"})  # a re-delivery must not overwrite the record
    assert [(m, e["text"]) for m, e in again.pending()] == [(5, "hello")]
    again.done(5)
    assert Inbox(path).pending() == []
    Inbox(path).done(99)  # unknown id is fine


def test_inbox_tolerates_a_corrupt_file(tmp_path: Path):
    path = tmp_path / "inbox.json"
    path.write_text("{broken", encoding="utf-8")
    assert Inbox(path).pending() == []
    Inbox(path).add(1, {"kind": "text", "text": "x"})
    assert len(Inbox(path).pending()) == 1


def test_capture_raw_keeps_journal_things_and_skips_other_commands():
    assert _capture_raw("just a thought") == "just a thought"
    assert _capture_raw("/book Atomic Habits | idea") == "book: Atomic Habits | idea"
    assert _capture_raw("/private@my_bot secret") == "private: secret"
    assert _capture_raw("/done 2") is None and _capture_raw("/ask what now") is None and _capture_raw("/brief") is None
    assert _capture_raw("/todo") is None and _capture_raw("   ") is None


import pytest


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "brain")


def _ctx(store, tmp_path):
    ctx = make_ctx(store)
    ctx.bot_data["inbox"] = Inbox(tmp_path / "inbox.json")
    return ctx


def test_a_message_is_on_disk_before_processing_and_removed_after_saving(store, tmp_path):
    ctx = _ctx(store, tmp_path)
    u = make_update(text="a long thought that should never be lost", message_id=200)
    run(_record_inbound(u, ctx))
    assert [m for m, _ in ctx.bot_data["inbox"].pending()] == [200]  # recorded first
    run(on_text(u, ctx))
    assert store.has("tg_200") and ctx.bot_data["inbox"].pending() == []


def test_a_crash_while_handling_leaves_the_message_in_the_inbox_and_it_is_recovered(store, tmp_path, monkeypatch):
    import secondbrain.bot.app as botapp
    ctx = _ctx(store, tmp_path)
    u = make_update(text="thought written just before a crash", message_id=201, date=datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc))
    run(_record_inbound(u, ctx))

    async def boom(*a, **k):
        raise RuntimeError("process died")

    monkeypatch.setattr(botapp, "_process_text", boom)
    try:
        run(on_text(u, ctx))
    except RuntimeError:
        pass
    assert not store.has("tg_201") and len(ctx.bot_data["inbox"].pending()) == 1
    monkeypatch.undo()

    sent = []
    bot = SimpleNamespace(send_message=lambda **k: _async_append(sent, k))
    app = SimpleNamespace(bot=bot, bot_data=ctx.bot_data)
    _age_everything(ctx.bot_data["inbox"])
    run(_replay_inbox(app))
    card = store.read_card("tg_201")
    assert card.key_points[0].text == "thought written just before a crash"
    assert card.consumed_at == datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)  # the time he wrote it, not the recovery time
    assert ctx.bot_data["inbox"].pending() == [] and "Recovered" in sent[0]["text"]


async def _async_append(lst, item):
    lst.append(item)


def _age_everything(inbox):
    data = inbox._load()
    for e in data.values():
        e["at"] = time.time() - 3600
    inbox._save(data)


def test_a_voice_note_that_fails_offline_is_kept_and_transcribed_later(store, tmp_path):
    ctx = _ctx(store, tmp_path)
    ctx.bot_data["transcriber"] = FakeTranscriber(fail=True)
    u = _voice_update(210)
    u.message.voice.file_id = "FILE-1"
    run(_record_inbound(u, ctx))
    run(on_voice(u, ctx))
    assert not store.has("tg_210")
    pending = ctx.bot_data["inbox"].pending()
    assert len(pending) == 1 and pending[0][1]["file_id"] == "FILE-1"

    class _File:
        async def download_as_bytearray(self):
            return bytearray(b"audio")

    async def get_file(file_id):
        assert file_id == "FILE-1"
        return _File()

    sent = []
    bot = SimpleNamespace(send_message=lambda **k: _async_append(sent, k), get_file=get_file)
    app = SimpleNamespace(bot=bot, bot_data=ctx.bot_data)
    ctx.bot_data["transcriber"] = FakeTranscriber("I was offline when I said this")
    _age_everything(ctx.bot_data["inbox"])
    run(_replay_inbox(app))
    assert store.read_card("tg_210").key_points[0].text == "I was offline when I said this"
    assert ctx.bot_data["inbox"].pending() == [] and "voice note" in sent[0]["text"]


def test_replay_skips_fresh_and_in_flight_messages_and_gives_up_politely(store, tmp_path):
    ctx = _ctx(store, tmp_path)
    inbox = ctx.bot_data["inbox"]
    inbox.add(220, {"kind": "text", "text": "fresh", "date": "2026-11-20T09:00:00+00:00", "reply": None})
    sent = []
    app = SimpleNamespace(bot=SimpleNamespace(send_message=lambda **k: _async_append(sent, k)), bot_data=ctx.bot_data)
    run(_replay_inbox(app))
    assert not store.has("tg_220")  # too fresh: the normal handler may still be working on it
    _age_everything(inbox)
    ctx.bot_data["inflight"] = {220}
    run(_replay_inbox(app))
    assert not store.has("tg_220")  # being handled right now
    ctx.bot_data["inflight"] = set()
    inbox.add(221, {"kind": "voice", "file_id": "X", "dur": 5, "date": "2026-11-20T09:00:00+00:00", "reply": None})
    data = inbox._load()
    data["221"]["at"], data["221"]["tries"] = time.time() - 3600, MAX_TRIES
    inbox._save(data)
    ctx.bot_data["transcriber"] = FakeTranscriber()
    run(_replay_inbox(app))
    assert any("could not process" in m["text"] for m in sent)
    assert inbox._load()["221"]["gave_up"] is True  # kept, not deleted, and only announced once
    n = len(sent)
    run(_replay_inbox(app))
    assert len(sent) == n and "221" in inbox._load()


def test_inbox_recorder_runs_first_in_its_own_handler_group(store):
    from secondbrain.bot.app import build_application
    app = build_application("123:abc", OWNER, store, "", store.root / "s.json")
    assert min(app.handlers) == -1 and any(h.callback is _record_inbound for h in app.handlers[-1])


class _OfflineMessage(FakeMessage):
    async def reply_text(self, text, **kwargs):
        from telegram.error import NetworkError
        raise NetworkError("httpx.ConnectError")


def test_a_failed_send_of_the_mentors_reply_keeps_the_reply_and_does_not_duplicate_the_note(store, tmp_path):
    from secondbrain.outbox import Outbox
    from secondbrain.bot.app import _flush_outbox

    class FakeState:
        def sent(self):
            return ["Are you coachable?"]

    class FakeMentor:
        state = FakeState()

        def awaiting(self):
            return "onboarding"

        def handle_onboarding_answer(self, text, when, message_id):
            store.write_card(__import__("secondbrain.bot.capture", fromlist=["parse_capture"]).parse_capture(
                text, when, message_id=message_id).model_copy(update={"id": f"mo_{message_id}"}))
            return "Here is my next question. Why this, and why now?"

        handle_commitments = handle_closeout = None

    ctx = _ctx(store, tmp_path)
    ctx.bot_data["outbox"] = Outbox(tmp_path / "outbox.json")
    ctx.bot_data["mentor"] = FakeMentor()
    u = make_update(text="a long paragraph about my whole life and my dreams", message_id=300)
    u.message.__class__ = _OfflineMessage
    run(_record_inbound(u, ctx))
    run(on_text(u, ctx))  # the reply fails to send
    assert store.has("mo_300")
    assert ctx.bot_data["inbox"].pending() == []                       # handled: must not be replayed as a duplicate
    assert ctx.bot_data["outbox"].pending() == [(1, "Here is my next question. Why this, and why now?")]

    sent = []
    bot = SimpleNamespace(send_message=lambda **k: _async_append(sent, k))
    app = SimpleNamespace(bot=bot, bot_data=ctx.bot_data)
    run(_flush_outbox(app))
    assert sent[0]["text"].startswith("Here is my next question") and ctx.bot_data["outbox"].pending() == []


def test_outbox_stays_queued_and_in_order_while_offline(tmp_path):
    from telegram.error import NetworkError
    from secondbrain.outbox import Outbox
    from secondbrain.bot.app import _flush_outbox

    box = Outbox(tmp_path / "o.json")
    box.add("first")
    box.add("second")

    async def fail(**k):
        raise NetworkError("down")

    app = SimpleNamespace(bot=SimpleNamespace(send_message=fail), bot_data={"outbox": box, "owner_id": OWNER})
    run(_flush_outbox(app))
    assert [t for _, t in box.pending()] == ["first", "second"]
    sent = []
    app.bot = SimpleNamespace(send_message=lambda **k: _async_append(sent, k["text"]))
    run(_flush_outbox(app))
    assert sent == ["first", "second"] and box.pending() == []


def test_replay_does_not_duplicate_a_note_the_mentor_already_saved(store, tmp_path):
    ctx = _ctx(store, tmp_path)
    inbox = ctx.bot_data["inbox"]
    inbox.add(310, {"kind": "text", "text": "already handled by the mentor", "date": "2026-11-20T09:00:00+00:00", "reply": None})
    from secondbrain.bot.capture import parse_capture
    store.write_card(parse_capture("already handled by the mentor", datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc),
                                   message_id=310).model_copy(update={"id": "mo_310"}))
    _age_everything(inbox)
    sent = []
    app = SimpleNamespace(bot=SimpleNamespace(send_message=lambda **k: _async_append(sent, k)), bot_data=ctx.bot_data)
    run(_replay_inbox(app))
    assert not store.has("tg_310") and inbox.pending() == []
