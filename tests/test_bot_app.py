import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from telegram.error import InvalidToken, NetworkError

from secondbrain.bot.app import (
    build_application,
    cmd_brief,
    cmd_start,
    configure_logging,
    due_jobs,
    is_owner,
    load_state,
    on_callback,
    on_text,
    redact,
    run_due_jobs,
    run_with_retries,
    save_state,
)
from secondbrain.schema import Action, Card, Relevance
from secondbrain.store import Store

OWNER = 1434918489
STRANGER = 999
IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 11, 18, 10, 0, tzinfo=IST)


class FakeMessage:
    def __init__(self, text="hello", message_id=None, date=None):
        self.text = text
        self.message_id = message_id
        self.date = date
        self.replies: list[tuple[str, dict]] = []

    async def reply_text(self, text, **kwargs):
        self.replies.append((text, kwargs))


class FakeQuery:
    def __init__(self, data):
        self.data = data
        self.answers: list = []
        self.markup_removed = False

    async def answer(self, text=None, **kw):
        self.answers.append(text)

    async def edit_message_reply_markup(self, reply_markup=None, **kw):
        self.markup_removed = True


def make_update(user_id=OWNER, chat_type="private", text="hello", data=None, chat_id=None, message_id=None, date=None):
    user = SimpleNamespace(id=user_id) if user_id is not None else None
    chat = SimpleNamespace(id=chat_id if chat_id is not None else (user_id or 0), type=chat_type)
    return SimpleNamespace(effective_user=user, effective_chat=chat, message=FakeMessage(text, message_id, date),
                           callback_query=FakeQuery(data) if data is not None else None)


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "brain")


def make_ctx(store: Store, owner_id=OWNER, goals="Focus: ship daily"):
    return SimpleNamespace(bot_data={"store": store, "goals_text": goals, "owner_id": owner_id, "now": lambda: NOW})


def run(coro):
    return asyncio.run(coro)


def action_card(id="yt_a") -> Card:
    return Card(id=id, source="youtube", type="consumed", title="Video", consumed_at=NOW - timedelta(days=1),
                topic={"primary": "infra/sre", "secondary": []},
                relevance=Relevance(bet_job=5, bet_product=5, actionability=5, novelty=5, quality=5, score=70),
                action=Action(text="Try it"))


# --- owner allowlist (Review Focus 2) ------------------------------------------------------------

def test_non_owner_message_gets_no_reply_and_no_card(store):
    u = make_update(user_id=STRANGER, text="idea: steal the memory")
    run(on_text(u, make_ctx(store)))
    assert u.message.replies == [] and list(store.iter_cards()) == []


def test_owner_message_creates_card_and_replies(store):
    u = make_update(text="idea: ship the brief")
    run(on_text(u, make_ctx(store)))
    cards = list(store.iter_cards())
    assert len(cards) == 1 and cards[0].type == "thought" and cards[0].visibility == "private"
    assert u.message.replies[0][0] == "Saved: thought"


def test_redelivered_message_does_not_duplicate_and_uses_the_message_date(store):
    sent_at = datetime(2026, 11, 17, 18, 20, tzinfo=timezone.utc)
    run(on_text(make_update(text="idea: late night thought", message_id=4242, date=sent_at), make_ctx(store)))
    later = make_ctx(store)
    later.bot_data["now"] = lambda: NOW + timedelta(hours=9)  # processed after a restart, next morning
    run(on_text(make_update(text="idea: late night thought", message_id=4242, date=sent_at), later))
    cards = list(store.iter_cards())
    assert len(cards) == 1 and cards[0].id == "tg_4242" and cards[0].consumed_at == sent_at


def test_owner_empty_prefix_gets_error_reply_and_no_card(store):
    u = make_update(text="idea:")
    run(on_text(u, make_ctx(store)))
    assert "couldn't save" in u.message.replies[0][0].lower() and list(store.iter_cards()) == []


def test_non_owner_callback_ignored(store):
    store.write_card(action_card())
    u = make_update(user_id=STRANGER, data="done:yt_a")
    run(on_callback(u, make_ctx(store)))
    assert store.read_card("yt_a").action.status == "open" and u.callback_query.answers == []


def test_owner_callback_applies_feedback_and_answers(store):
    store.write_card(action_card())
    u = make_update(data="done:yt_a")
    run(on_callback(u, make_ctx(store)))
    assert store.read_card("yt_a").action.status == "done"
    assert u.callback_query.answers and u.callback_query.markup_removed


def test_owner_id_none_rejects_everyone():
    assert is_owner(make_update(user_id=OWNER), None) is False
    assert is_owner(make_update(user_id=0), None) is False


def test_is_owner_requires_matching_user_and_private_chat():
    assert is_owner(make_update(), OWNER) is True
    assert is_owner(make_update(user_id=STRANGER), OWNER) is False
    assert is_owner(make_update(chat_type="group"), OWNER) is False
    assert is_owner(make_update(chat_type="supergroup"), OWNER) is False
    assert is_owner(make_update(user_id=None), OWNER) is False
    assert is_owner(SimpleNamespace(effective_user=SimpleNamespace(id=OWNER), effective_chat=None), OWNER) is False


def test_stranger_commands_get_no_reply(store):
    for handler in (cmd_start, cmd_brief):
        u = make_update(user_id=STRANGER)
        run(handler(u, make_ctx(store)))
        assert u.message.replies == []


def test_owner_commands_reply(store):
    store.write_card(action_card())
    u = make_update()
    run(cmd_start(u, make_ctx(store)))
    assert "online" in u.message.replies[0][0].lower()
    u = make_update()
    run(cmd_brief(u, make_ctx(store)))
    text, kwargs = u.message.replies[0]
    assert "Today's one action" in text and "Try it" in text and kwargs.get("reply_markup") is not None


# --- secrets in logs -----------------------------------------------------------------------------

def test_redact_removes_token():
    token = "123456:ABC-secret"
    assert token not in redact(f"Failed https://api.telegram.org/bot{token}/getMe", token)
    assert redact("nothing here", token) == "nothing here"
    assert redact("x", "") == "x"


def test_configure_logging_silences_httpx_so_token_urls_are_not_logged(caplog):
    configure_logging()
    with caplog.at_level(logging.INFO):
        logging.getLogger("httpx").info("HTTP Request: POST https://api.telegram.org/bot123456:SECRET/getUpdates")
        logging.getLogger("httpcore").debug("connect bot123456:SECRET")
    assert "SECRET" not in caplog.text


def test_configure_logging_can_write_to_a_file_without_httpx_noise(tmp_path: Path):
    log_file = tmp_path / "logs" / "bot.log"
    configure_logging(log_file=log_file)
    try:
        logging.getLogger("secondbrain.bot").warning("hello from the bot")
        logging.getLogger("httpx").info("POST https://api.telegram.org/bot123456:SECRET/getUpdates")
        for h in logging.getLogger().handlers:
            h.flush()
        text = log_file.read_text(encoding="utf-8")
        assert "hello from the bot" in text and "SECRET" not in text
        configure_logging(log_file=log_file)  # calling twice must not duplicate lines
        logging.getLogger("secondbrain.bot").warning("only once")
        for h in logging.getLogger().handlers:
            h.flush()
        assert log_file.read_text(encoding="utf-8").count("only once") == 1
    finally:
        for h in list(logging.getLogger().handlers):
            if isinstance(h, logging.FileHandler):
                logging.getLogger().removeHandler(h)
                h.close()


TOKEN = "123456:SECRET-TOKEN-abc"


def test_configure_logging_redacts_the_token_in_every_handler(tmp_path: Path):
    log_file = tmp_path / "bot.log"
    configure_logging(log_file=log_file, token=TOKEN)
    try:
        logging.getLogger("secondbrain.bot").error("boom %s via https://api.telegram.org/bot%s/getMe", "x", TOKEN)
        for h in logging.getLogger().handlers:
            h.flush()
        text = log_file.read_text(encoding="utf-8")
        assert TOKEN not in text and "<token>" in text
    finally:
        for h in list(logging.getLogger().handlers):
            if isinstance(h, logging.FileHandler):
                logging.getLogger().removeHandler(h)
                h.close()


def test_run_with_retries_backs_off_then_succeeds():
    attempts = {"n": 0}
    sleeps: list[float] = []

    def run_once():
        attempts["n"] += 1
        if attempts["n"] <= 2:
            raise NetworkError("offline")

    assert run_with_retries(run_once, TOKEN, sleep=sleeps.append) == 0
    assert sleeps == [5, 10] and attempts["n"] == 3


def test_run_with_retries_caps_the_delay():
    attempts = {"n": 0}
    sleeps: list[float] = []

    def run_once():
        attempts["n"] += 1
        if attempts["n"] <= 10:
            raise NetworkError("offline")

    run_with_retries(run_once, TOKEN, sleep=sleeps.append)
    assert sleeps[:7] == [5, 10, 20, 40, 80, 160, 300] and max(sleeps) == 300


def test_run_with_retries_invalid_token_stops_with_code_2_and_never_logs_the_token(caplog):
    sleeps: list[float] = []

    def run_once():
        raise InvalidToken(f"The token `{TOKEN}` was rejected by the server.")

    with caplog.at_level(logging.INFO):
        assert run_with_retries(run_once, TOKEN, sleep=sleeps.append) == 2
    assert sleeps == [] and TOKEN not in caplog.text


def test_run_with_retries_redacts_the_token_in_network_errors(caplog):
    attempts = {"n": 0}

    def run_once():
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise NetworkError(f"boom while calling bot{TOKEN}/getMe")

    with caplog.at_level(logging.INFO):
        assert run_with_retries(run_once, TOKEN, sleep=lambda s: None) == 0
    assert TOKEN not in caplog.text and "NetworkError" in caplog.text


def test_run_with_retries_lets_keyboard_interrupt_through():
    def run_once():
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_with_retries(run_once, TOKEN, sleep=lambda s: None)


# --- scheduling ----------------------------------------------------------------------------------

def at(hour, minute=0, day=18):
    return datetime(2026, 11, day, hour, minute, tzinfo=IST)


def test_due_jobs_windows():
    assert due_jobs(at(5, 59), {}) == []
    assert due_jobs(at(6, 0), {}) == ["morning"]
    assert due_jobs(at(15, 0), {}) == ["morning"]   # laptop was off earlier: a late start still gets the brief
    assert due_jobs(at(20, 59), {}) == ["morning"]
    assert due_jobs(at(21, 0), {}) == []            # too late for a morning brief
    assert due_jobs(at(21, 29), {}) == []
    assert due_jobs(at(21, 30), {}) == ["evening"]
    assert due_jobs(at(23, 59), {}) == ["evening"]


def test_due_jobs_not_repeated_same_day_but_due_next_day():
    state = {"morning": "2026-11-18", "evening": "2026-11-18"}
    assert due_jobs(at(10), state) == [] and due_jobs(at(22), state) == []
    assert due_jobs(at(10, day=19), state) == ["morning"]


def test_state_roundtrip_and_corrupt_file(tmp_path: Path):
    p = tmp_path / "state.json"
    assert load_state(p) == {}
    save_state(p, {"morning": "2026-11-18"})
    assert load_state(p) == {"morning": "2026-11-18"}
    p.write_text("{broken", encoding="utf-8")
    assert load_state(p) == {}
    p.write_text("[1,2]", encoding="utf-8")
    assert load_state(p) == {}


def test_run_due_jobs_sends_once_and_persists_state(store, tmp_path: Path):
    sent: list[tuple[str, str]] = []

    async def send(name, brief):
        sent.append((name, brief.text))

    state = tmp_path / "state.json"
    assert run(run_due_jobs(send, store, "Focus: ship", NOW, state)) == ["morning"]
    assert run(run_due_jobs(send, store, "Focus: ship", NOW, state)) == []
    assert [n for n, _ in sent] == ["morning"] and "Today's one action" in sent[0][1]
    assert load_state(state) == {"morning": "2026-11-18"}


def test_run_due_jobs_send_failure_is_not_marked_sent_and_retries(store, tmp_path: Path):
    calls = {"n": 0}

    async def flaky(name, brief):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("offline")

    state = tmp_path / "state.json"
    assert run(run_due_jobs(flaky, store, "", NOW, state)) == []
    assert load_state(state) == {}
    assert run(run_due_jobs(flaky, store, "", NOW, state)) == ["morning"]


def test_run_due_jobs_evening_window(store, tmp_path: Path):
    sent = []

    async def send(name, brief):
        sent.append(name)

    run(run_due_jobs(send, store, "", at(22), tmp_path / "s.json"))
    assert sent == ["evening"]


# --- wiring --------------------------------------------------------------------------------------

def test_build_application_smoke_without_network(store, tmp_path: Path):
    app = build_application("123456:ABCdefGhIJKlmNoPQRsTUVwxyZ", OWNER, store, "Focus: x", tmp_path / "state.json")
    handlers = [h for group in app.handlers.values() for h in group]
    assert len(handlers) >= 5
    assert app.bot_data["owner_id"] == OWNER and app.bot_data["store"] is store


def test_build_application_refuses_missing_owner(store, tmp_path: Path):
    with pytest.raises(ValueError):
        build_application("123456:ABCdefGhIJKlmNoPQRsTUVwxyZ", None, store, "", tmp_path / "s.json")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        build_application("", OWNER, store, "", tmp_path / "s.json")


def _three_todos(store):
    for i, text in enumerate(("Alpha task", "Beta task", "Gamma task")):
        store.write_card(Card(id=f"tg_{i}", source="telegram", type="thought", title=text,
                              consumed_at=NOW - timedelta(hours=i + 1),
                              topic={"primary": "uncertain"}, action=Action(text=text)))


def test_skip_command_drops_a_numbered_line_from_the_last_brief(store):
    from secondbrain.bot.app import _mark_command
    _three_todos(store)
    ctx = make_ctx(store)
    run(cmd_brief(make_update(), ctx))
    ids = ctx.bot_data["last_ids"]
    assert len(ids) == 3
    ctx.args = ["2"]
    u = make_update()
    run(_mark_command("skip")(u, ctx))
    assert store.read_card(ids[1]).action.status == "skipped"
    assert u.message.replies[0][0].startswith("Dropped:")
    ctx.args = ["9"]
    u = make_update()
    run(_mark_command("done")(u, ctx))
    assert "no item 9" in u.message.replies[0][0].lower()


def test_done_command_works_after_a_restart_and_ignores_strangers(store):
    from secondbrain.bot.app import _mark_command
    _three_todos(store)
    ctx = make_ctx(store)  # no last_ids: as after a bot restart
    ctx.args = ["1"]
    run(_mark_command("done")(make_update(), ctx))
    assert any(store.read_card(f"tg_{i}").action.status == "done" for i in range(3))
    stranger = make_update(user_id=STRANGER)
    run(_mark_command("done")(stranger, ctx))
    assert stranger.message.replies == []


def test_summary_command_explains_and_shows_numbers(store):
    from secondbrain.bot.app import cmd_summary
    _three_todos(store)
    ctx = make_ctx(store)
    ctx.bot_data["state_path"] = store.root / "raw" / "bot_state.json"
    u = make_update()
    run(cmd_summary(u, ctx))
    text = u.message.replies[0][0]
    assert "HOW YOUR SECOND BRAIN WORKS" in text and "Cards: 3" in text and len(text) < 4000


def test_ask_command_answers_and_logs(store):
    from secondbrain.bot.app import cmd_ask
    ctx = make_ctx(store)
    ctx.bot_data["ask_runner"] = lambda system, prompt: "Do the hard thing first."
    ctx.args = ["should", "I", "apply?"]
    u = make_update(text="/ask should I apply?", message_id=55)
    run(cmd_ask(u, ctx))
    texts = [r[0] for r in u.message.replies]
    assert texts[-1] == "Do the hard thing first." and store.has("adv_55")


def test_ask_without_question_and_strangers(store):
    from secondbrain.bot.app import cmd_ask
    ctx = make_ctx(store)
    ctx.bot_data["ask_runner"] = lambda s, p: "x"
    ctx.args = []
    u = make_update(text="/ask")
    run(cmd_ask(u, ctx))
    assert u.message.replies[0][0].startswith("Could not answer")
    s = make_update(user_id=STRANGER, text="/ask hi")
    ctx.args = ["hi"]
    run(cmd_ask(s, ctx))
    assert s.message.replies == []


def test_private_and_journal_prefixes_reply_correctly(store):
    u = make_update(text="private: secret thing", message_id=70)
    run(on_text(u, make_ctx(store)))
    assert "never sent to Claude" in u.message.replies[0][0]
    u = make_update(text="journal: today was long", message_id=71)
    run(on_text(u, make_ctx(store)))
    assert u.message.replies[0][0] == "Saved: thought"


def test_slash_capture_commands_save_cards_and_keep_line_breaks(store):
    from secondbrain.bot.app import _capture_command
    ctx = make_ctx(store)
    ctx.args = []
    u = make_update(text="/journal line one\nline two", message_id=80)
    run(_capture_command("journal")(u, ctx))
    assert u.message.replies[0][0] == "Saved: thought"
    assert store.read_card("tg_80").key_points[0].text == "line one\nline two"
    u = make_update(text="/private@my_bot hidden", message_id=81)
    run(_capture_command("private")(u, ctx))
    assert "never sent to Claude" in u.message.replies[0][0] and store.read_card("tg_81").channel == "local-only"
    u = make_update(text="/made", message_id=82)
    run(_capture_command("made")(u, ctx))
    assert "Write it after the command" in u.message.replies[0][0] and not store.has("tg_82")
    u = make_update(user_id=STRANGER, text="/todo x", message_id=83)
    run(_capture_command("todo")(u, ctx))
    assert u.message.replies == [] and not store.has("tg_83")


def test_done_command_logs_text_but_still_marks_numbers(store):
    from secondbrain.bot.app import _mark_command
    ctx = make_ctx(store)
    ctx.args = ["fixed", "the", "login"]
    u = make_update(text="/done fixed the login", message_id=90)
    run(_mark_command("done")(u, ctx))
    card = store.read_card("tg_90")
    assert card.type == "acted" and card.title == "fixed the login"
    ctx.args = ["skip-me"]
    u = make_update(text="/skip skip-me")
    run(_mark_command("skip")(u, ctx))
    assert u.message.replies[0][0].startswith("Use it like: /skip 2")


def test_all_capture_commands_are_registered(store):
    from secondbrain.bot.app import CAPTURE_COMMANDS
    app = build_application("123:abc", OWNER, store, "", store.root / "s.json")
    names = {c for h in app.handlers[0] if hasattr(h, "commands") for c in h.commands}
    assert set(CAPTURE_COMMANDS) <= names and {"ask", "brief", "summary", "skip"} <= names and not {"later", "evening", "journal"} & names


def test_book_command_keeps_the_whole_reading_log(store):
    from secondbrain.bot.app import _capture_command
    ctx = make_ctx(store)
    ctx.args = []
    text = "/book Atomic Habits ch3: habits are identity.\n\nIdea: build a habit tracker for interview prep.\n\nUnderstood: small wins compound."
    u = make_update(text=text, message_id=95)
    run(_capture_command("book")(u, ctx))
    card = store.read_card("tg_95")
    assert card.type == "book" and u.message.replies[0][0] == "Saved: book"
    assert [k.text for k in card.key_points][1] == "Idea: build a habit tracker for interview prep."
    assert len(card.key_points) == 3


def test_new_idea_gets_related_older_notes_and_stays_quiet_when_nothing_matches(store):
    from secondbrain.bot.app import on_text

    class FakeIndex:
        def __init__(self, hits):
            self.hits, self.calls = hits, []

        def related(self, text, k, min_cosine, exclude):
            self.calls.append((text, exclude))
            return self.hits

    from secondbrain.index import Hit
    ctx = make_ctx(store)
    ctx.bot_data["index"] = FakeIndex([Hit("old1", "Habit tracker idea", "track daily habits", 0.7)])
    u = make_update(text="I want to build a habit tracker for interviews", message_id=96)
    run(on_text(u, ctx))
    assert u.message.replies[0][0] == "Saved: thought"
    assert "written about this before" in u.message.replies[1][0] and "Habit tracker idea" in u.message.replies[1][0]
    assert ctx.bot_data["index"].calls[0][1] == frozenset({"tg_96"})  # never suggests the note itself

    ctx.bot_data["index"] = FakeIndex([])
    u = make_update(text="Another thought with nothing similar at all", message_id=97)
    run(on_text(u, ctx))
    assert len(u.message.replies) == 1

    u = make_update(text="todo: buy milk and eggs from the shop today", message_id=98)
    ctx.bot_data["index"] = FakeIndex([Hit("old1", "x", "y", 0.9)])
    run(on_text(u, ctx))
    assert len(u.message.replies) == 1  # a todo is not an idea


def _reply_to(update, text, is_bot=True):
    update.message.reply_to_message = SimpleNamespace(text=text, caption=None, from_user=SimpleNamespace(is_bot=is_bot))
    return update


def test_a_reply_is_saved_with_the_message_it_answers(store):
    from secondbrain.bot.app import on_text
    ctx = make_ctx(store)
    question = "Are you coachable? Will you tell me the truth and do what you say?"
    u = _reply_to(make_update(text="Yes, I am coachable", message_id=120), question)
    run(on_text(u, ctx))
    card = store.read_card("tg_120")
    assert card.reply_to == question and card.key_points[0].text == "Yes, I am coachable"
    plain = make_update(text="Just a normal note, no reply here", message_id=121)
    run(on_text(plain, ctx))
    assert store.read_card("tg_121").reply_to is None


def test_a_selected_quote_wins_over_the_whole_replied_message(store):
    from secondbrain.bot.app import _reply_context
    msg = SimpleNamespace(quote=SimpleNamespace(text="the second question"),
                          reply_to_message=SimpleNamespace(text="first question. the second question. third", caption=None))
    assert _reply_context(msg) == "the second question"


def test_reply_context_scrubs_secrets_and_is_capped():
    from secondbrain.bot.app import _reply_context
    msg = SimpleNamespace(reply_to_message=SimpleNamespace(text="key sk-ant-api03-abcdefghijklmnopqrstuvwx " + "x" * 600, caption=None))
    out = _reply_context(msg)
    assert "sk-ant" not in out and len(out) <= 400


def test_reply_to_an_old_message_is_not_taken_as_the_mentors_answer(store):
    from secondbrain.bot.app import on_text

    class FakeState:
        def sent(self):
            return ["Are you coachable? Will you tell me the truth?"]

    class FakeMentor:
        state = FakeState()
        answered: list = []

        def awaiting(self):
            return "onboarding"

        def handle_onboarding_answer(self, text, when, message_id):
            self.answered.append(text)
            return "mentor reply"

        handle_commitments = handle_closeout = None

    mentor = FakeMentor()
    ctx = make_ctx(store)
    ctx.bot_data["mentor"] = mentor
    # replying to the mentor's latest message -> goes to the mentor flow
    u = _reply_to(make_update(text="Yes I am", message_id=130), "Hello Daksh. Are you coachable? Will you tell me the truth?")
    run(on_text(u, ctx))
    assert mentor.answered == ["Yes I am"] and u.message.replies[-1][0] == "mentor reply"
    # replying to something else (an old brief) -> NOT the mentor's answer; saved as a note with that context
    u = _reply_to(make_update(text="Item 2 is wrong, I already did it", message_id=131), "Morning brief: 1. Apply to two jobs 2. Fix login")
    run(on_text(u, ctx))
    assert mentor.answered == ["Yes I am"]
    assert store.read_card("tg_131").reply_to.startswith("Morning brief")
