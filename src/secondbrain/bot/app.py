"""Telegram bot: owner-only handlers, daily brief scheduler, and secret-safe logging."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time as time_module
from collections.abc import Awaitable, Callable
from datetime import date, datetime, time, timedelta
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import InvalidToken, TelegramError
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from ..store import Store
from .brief import Brief, apply_feedback, build_evening_checkin, build_morning_brief
from .. import usage
from ..advisor import AdviceError, ask as ask_advice
from ..schema import Topic
from ..sessions import redact_secrets
from .capture import _PREFIX as _PREFIX_RE, parse_capture
from .classify import MIN_CHARS
from .summary import build_summary

log = logging.getLogger("secondbrain.bot")

MORNING_WINDOW = (time(6, 0), time(21, 0))   # first chance after 06:00, until 21:00: a late start still gets its brief
EVENING_FROM = time(21, 30)                  # send from 21:30 until midnight
SCHEDULER_INTERVAL_SECONDS = 60


# --- security helpers ----------------------------------------------------------------------------

def is_owner(update, owner_id: int | None) -> bool:
    """True only for the owner, in a private chat. Everything else is ignored silently."""
    if owner_id is None:
        return False
    user = getattr(update, "effective_user", None)
    chat = getattr(update, "effective_chat", None)
    if user is None or chat is None:
        return False
    return user.id == owner_id and chat.type == "private"


def redact(text: str, token: str) -> str:
    return text.replace(token, "<token>") if token else text


_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


class _TokenRedactingFilter(logging.Filter):
    """Last line of defence: scrub the bot token from any record, including tracebacks."""

    def __init__(self, token: str):
        super().__init__()
        self._token = token

    def filter(self, record: logging.LogRecord) -> bool:
        if not self._token:
            return True
        try:
            message = record.getMessage()
        except Exception:
            return True
        if self._token in message:
            record.msg, record.args = redact(message, self._token), ()
        if record.exc_info:
            text = logging.Formatter().formatException(record.exc_info)
            record.exc_text = redact(text, self._token)
            record.exc_info = None
        return True


def configure_logging(log_file: Path | None = None, token: str | None = None) -> None:
    """The HTTP libraries log request URLs, and Telegram URLs contain the bot token: keep them quiet.

    With log_file set (needed under pythonw, which has no console) records also go to that file.
    With token set, every handler also scrubs the token from whatever it writes.
    """
    logging.basicConfig(level=logging.INFO, format=_LOG_FORMAT)
    for name in ("httpx", "httpcore", "telegram", "telegram.ext"):
        logging.getLogger(name).setLevel(logging.WARNING)
    if log_file is not None:
        root = logging.getLogger()
        for h in list(root.handlers):  # replace any file handler from an earlier call: no duplicate lines
            if isinstance(h, logging.FileHandler):
                root.removeHandler(h)
                h.close()
        log_file = Path(log_file)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_file, encoding="utf-8")
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        root.addHandler(handler)
    if token:
        for h in logging.getLogger().handlers:
            for old in [f for f in h.filters if isinstance(f, _TokenRedactingFilter)]:
                h.removeFilter(old)
            h.addFilter(_TokenRedactingFilter(token))


# --- handlers ------------------------------------------------------------------------------------

def _markup(brief: Brief) -> InlineKeyboardMarkup | None:
    if not brief.buttons:
        return None
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=data) for label, data in brief.buttons]])


HELP_TEXT = """Second brain online.

Just type. Anything you send (a thought, a journal entry, what you learned from a book, a link) is saved automatically.

Commands, only where the bot must act differently:
/brief - today's plan
/book <text> - your reading log: what you read, learned, understood, ideas to try (or: Title | learned | how I'll use it)
/todo <task> - put a task on your list
/done <thing> - log something you finished (or /done 2 to tick line 2 of the brief)
/skip 2 - drop line 2 of the brief
/ask <question> - personal advice from Claude, using your notes
/private <text> - saved, but never sent to Claude
/usage - Claude calls and tokens per section (for the quota)
/summary - how it all works + live numbers"""


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_owner(update, context.bot_data.get("owner_id")) or update.message is None:
        return
    await update.message.reply_text(HELP_TEXT)


async def cmd_brief(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    d = context.bot_data
    if not is_owner(update, d.get("owner_id")) or update.message is None:
        return
    brief = build_morning_brief(d["store"], d.get("goals_text", ""), d["now"](), d.get("focus_projects"))
    _remember_ids(d, brief.ids)
    await update.message.reply_text(brief.text, reply_markup=_markup(brief))


async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    d = context.bot_data
    if not is_owner(update, d.get("owner_id")) or update.message is None:
        return
    sync_log = Path(d["state_path"]).parent / "sync.log"
    await update.message.reply_text(build_summary(d["store"], d["now"](), sync_log))


_COMMAND_HEAD = re.compile(r"^\s*/\w+(?:@\w+)?\s*", re.DOTALL)
CAPTURE_COMMANDS = ("private", "todo", "done", "book")


def _body(message, context) -> str:
    """Text after the /command, keeping line breaks (context.args would flatten a long journal entry)."""
    text = getattr(message, "text", "") or ""
    if text.lstrip().startswith("/"):
        return _COMMAND_HEAD.sub("", text, count=1).strip()
    return " ".join(getattr(context, "args", None) or [])


RELATED_TYPES = ("thought", "friction", "experiment", "book", "decided")
RELATED_MIN_CHARS = 25


async def _suggest_related(update: Update, d, card) -> None:
    """Reply with older notes that mean something similar to a new idea/problem. Local only, best effort, silent if none."""
    index = d.get("index")
    if index is None or card is None or card.type not in RELATED_TYPES or not card.key_points:
        return
    if card.type == "thought" and card.action:  # a todo, not an idea
        return
    text = " ".join(k.text for k in card.key_points)
    if len(text.strip()) < RELATED_MIN_CHARS:
        return
    try:
        hits = await asyncio.to_thread(index.related, text[:2000], 3, 0.55, frozenset({card.id}))
    except Exception as e:  # the note is already saved; a failed lookup must never show as an error
        log.warning("related-notes lookup failed: %s", type(e).__name__)
        return
    if not hits:
        return
    lines = ["You have written about this before:"]
    for h in hits:
        snippet = " ".join(h.snippet.split())[:140]
        lines.append(f"- {h.title[:80]}" + (f": {snippet}" if snippet and snippet != h.title[:len(snippet)] else ""))
    await update.message.reply_text("\n".join(lines))


def _reply_context(message) -> str | None:
    """The text this message is a reply to (the quoted part if he selected one), or None. Secrets are scrubbed."""
    quote = getattr(getattr(message, "quote", None), "text", None)
    target = getattr(message, "reply_to_message", None)
    text = quote or getattr(target, "text", None) or getattr(target, "caption", None)
    if not text or not text.strip():
        return None
    return redact_secrets(" ".join(text.split()))[:400]


def _is_reply_to_latest_mentor_message(message, mentor) -> bool:
    """True when this is not a reply at all, or it answers the mentor's most recent message."""
    replied = _reply_context(message)
    if replied is None:
        return getattr(message, "reply_to_message", None) is None  # a reply to a photo etc. is still a reply
    sent = mentor.state.sent()
    if not sent:
        return False
    latest = " ".join(sent[-1].split())[:60]
    return bool(latest) and latest in replied


async def _save_capture(update: Update, d, raw: str):
    message = update.message
    when = getattr(message, "date", None) or d["now"]()  # the message's own send time, not processing time
    try:
        card = parse_capture(raw, when, message_id=getattr(message, "message_id", None),
                             reply_to=_reply_context(message))
    except ValueError:
        await message.reply_text("I couldn't save that: there was no text after the command.")
        return None
    d["store"].write_card(card)
    label = "privately (never sent to Claude)" if card.channel == "local-only" else card.type
    await message.reply_text(f"Saved: {label}")
    return card


async def _reclassify(d, card) -> None:
    """Background: the local model relabels an untagged message (journal / book / friction / ...). Best effort."""
    try:
        def run():
            with usage.section("classify"):
                return d["classifier"](card.key_points[0].text)

        kind, topic = await asyncio.to_thread(run)
        fresh = d["store"].read_card(card.id)
        d["store"].write_card(fresh.model_copy(update={"type": kind, "topic": Topic(primary=topic, secondary=[])}))
    except Exception as e:  # the card is already saved as a plain thought; never break the bot over a label
        log.warning("could not label %s: %s", card.id, type(e).__name__)


def _capture_command(kind: str):
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        d = context.bot_data
        if not is_owner(update, d.get("owner_id")) or update.message is None:
            return
        body = _body(update.message, context)
        if not body:
            await update.message.reply_text(f"Write it after the command, like: /{kind} your text")
            return
        card = await _save_capture(update, d, f"{kind}: {body}")
        if kind in ("book", "private"):
            await _suggest_related(update, d, card)
    return handler


def _remember_ids(d, ids: list[str]) -> None:
    d["last_ids"] = ids
    path = d.get("state_path")
    if path:
        state = load_state(path)
        state["last_ids"] = ",".join(ids)
        save_state(path, state)


def _recall_ids(d) -> list[str] | None:
    if d.get("last_ids") is not None:
        return d["last_ids"]
    path = d.get("state_path")
    raw = load_state(path).get("last_ids") if path else None
    return [i for i in raw.split(",") if i] if raw is not None else None


def _local_time(message, d) -> datetime:
    """The message's own send time in the bot's local timezone (Telegram sends UTC; mentor days are local)."""
    local = d["now"]()
    sent = getattr(message, "date", None)
    return sent.astimezone(local.tzinfo) if sent is not None and local.tzinfo is not None else (sent or local)


async def cmd_usage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    d = context.bot_data
    if not is_owner(update, d.get("owner_id")) or update.message is None:
        return
    path = Path(d["state_path"]).parent / "usage.jsonl"
    text = usage.report_text(path, 1, d["now"]()) + "\n\n----\n\n" + usage.report_text(path, 7, d["now"]())
    for part in _chunks(text):
        await update.message.reply_text(part)


async def _mentor_route(update: Update, d, mentor) -> bool:
    """Hand a plain message to the mentor flow when it is waiting for an answer. True = handled."""
    awaiting = mentor.awaiting()
    handler = {"onboarding": mentor.handle_onboarding_answer, "commitments": mentor.handle_commitments,
               "closeout": mentor.handle_closeout}.get(awaiting)
    if handler is None:
        return False
    message = update.message
    if not _is_reply_to_latest_mentor_message(message, mentor):
        return False  # he is replying to some OTHER message: save it as a note with that context, not as the answer
    when = _local_time(message, d)
    try:
        reply = await asyncio.to_thread(handler, message.text, when, getattr(message, "message_id", None))
    except Exception as e:  # never lose his message because the mentor failed: fall through to normal capture
        log.warning("mentor flow failed (%s): %s", awaiting, type(e).__name__)
        return False
    if reply is None:
        return False
    for part in _chunks(reply):
        await message.reply_text(part)
    return True


def _chunks(text: str, size: int = 3900) -> list[str]:
    return [text[i:i + size] for i in range(0, len(text), size)] or [""]


async def cmd_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    d = context.bot_data
    if not is_owner(update, d.get("owner_id")) or update.message is None:
        return
    message = update.message
    question = _body(message, context)
    when = _local_time(message, d)
    runner = d.get("ask_runner")
    kwargs = {"runner": runner} if runner else {}
    kwargs["index"] = d.get("index")
    if question:
        await message.reply_text("Thinking... (usually under a minute)")
    mentor = d.get("mentor")
    try:
        if mentor is not None and not runner:
            answer = await asyncio.to_thread(mentor.ask, question, when, getattr(message, "message_id", None))
        else:
            answer = await asyncio.to_thread(ask_advice, d["store"], question, d.get("goals_text", ""), when,
                                             getattr(message, "message_id", None), **kwargs)
    except AdviceError as e:
        await message.reply_text(f"Could not answer: {e}")
        return
    for part in _chunks(answer):
        await message.reply_text(part)


def _mark_command(verb: str):
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        d = context.bot_data
        if not is_owner(update, d.get("owner_id")) or update.message is None:
            return
        args = context.args or []
        if verb == "done" and args and not (len(args) == 1 and args[0].isdigit()):
            await _save_capture(update, d, f"done: {_body(update.message, context)}")  # /done fixed the login bug
            return
        if len(args) != 1 or not args[0].isdigit():
            await update.message.reply_text(
                f"Use it like: /{verb} 2  (the number of a line in the last /brief)."
                + ("  Or /done <what you finished> to log it." if verb == "done" else ""))
            return
        ids = _recall_ids(d)
        if ids is None:  # never sent a brief: build one now
            ids = build_morning_brief(d["store"], d.get("goals_text", ""), d["now"](), d.get("focus_projects")).ids
            _remember_ids(d, ids)
        n = int(args[0])
        if not 1 <= n <= len(ids):
            await update.message.reply_text(f"There is no item {n}. The last brief had {len(ids)}.")
            return
        card = d["store"].read_card(ids[n - 1])
        apply_feedback(d["store"], f"{verb}:{ids[n - 1]}")
        label = {"done": "Done", "later": "Parked for later", "skip": "Dropped"}[verb]
        await update.message.reply_text(f"{label}: {(card.action.text if card.action else card.title)[:120]}")
    return handler


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    d = context.bot_data
    if not is_owner(update, d.get("owner_id")) or update.message is None or not update.message.text:
        return
    raw = update.message.text
    mentor = d.get("mentor")
    if mentor is not None and await _mentor_route(update, d, mentor):
        return
    card = await _save_capture(update, d, raw)
    await _suggest_related(update, d, card)
    classifier = d.get("classifier")
    untagged = not _PREFIX_RE.match(raw)
    if (card is not None and classifier and untagged and card.type == "thought" and card.channel != "local-only"
            and len(raw.strip()) >= MIN_CHARS):
        task = asyncio.create_task(_reclassify(d, card))
        tasks = d.setdefault("tasks", set())
        tasks.add(task)
        task.add_done_callback(tasks.discard)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    d = context.bot_data
    query = update.callback_query
    if query is None or not is_owner(update, d.get("owner_id")):
        return
    apply_feedback(d["store"], query.data or "")
    await query.answer("Noted")
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except TelegramError:
        pass  # message already changed or too old: the feedback itself was recorded


async def _on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    token = context.bot_data.get("token", "")
    log.warning("bot error: %s", redact(f"{type(context.error).__name__}: {context.error}", token))


# --- scheduling ----------------------------------------------------------------------------------

def load_state(path: Path) -> dict[str, str]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}


def save_state(path: Path, state: dict[str, str]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(json.dumps(state), encoding="utf-8")
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def due_jobs(now: datetime, state: dict[str, str]) -> list[str]:
    today = now.date().isoformat()
    t = now.time()
    due: list[str] = []
    if MORNING_WINDOW[0] <= t < MORNING_WINDOW[1] and state.get("morning") != today:
        due.append("morning")
    if t >= EVENING_FROM and state.get("evening") != today:
        due.append("evening")
    return due


async def run_due_jobs(
    send: Callable[[str, Brief], Awaitable[None]],
    store: Store,
    goals_text: str,
    now: datetime,
    state_path: Path,
    focus_projects: tuple[str, ...] | None = None,
) -> list[str]:
    """Send whatever is due (once per day). A failed send is not marked as sent, so the next tick retries."""
    state = load_state(state_path)
    sent: list[str] = []
    for name in due_jobs(now, state):
        brief = build_morning_brief(store, goals_text, now, focus_projects) if name == "morning" else build_evening_checkin(now)
        try:
            await send(name, brief)
        except Exception as e:  # network trouble must not kill the scheduler
            log.warning("could not send %s message: %s", name, type(e).__name__)
            continue
        state = load_state(state_path)  # reload: sending may have stored the brief's numbering
        state[name] = now.date().isoformat()
        save_state(state_path, state)
        sent.append(name)
    return sent


SYNC_STALE_HOURS = 12
ALERT_GAP_DAYS = {"backup": 7}  # everything else: at most once a day


def due_alerts(now: datetime, state: dict[str, str], sync_log: Path) -> list[tuple[str, str]]:
    """Problems he must hear about instead of finding a stale brief: failed or missing sync, backup not working."""
    try:
        last = Path(sync_log).read_text(encoding="utf-8").strip().splitlines()[-1]
        parts = [p.strip() for p in last.split(" | ")]
        stamp = datetime.fromisoformat(parts[0])
    except (OSError, IndexError, ValueError):
        return []  # never ran yet: nothing to compare against
    found: list[tuple[str, str]] = []
    if parts[-1] != "exit=0":
        found.append(("sync_failed", "Your latest work has not been added to your memory since the last update failed. "
                                     "Worth a look next time you're at your computer."))
    elif now - stamp > timedelta(hours=SYNC_STALE_HOURS):
        found.append(("sync_stale", f"Your memory has not updated since {stamp:%d %b, %H:%M}. "
                                    "New work will not show up until it runs again."))
    if "backup: not set up" in parts:
        found.append(("backup", "Your notes are not backed up yet, so they exist only on your computer. "
                                "Worth setting one up next time you're at your computer."))
    if any(p.startswith("backup: failed") for p in parts):
        found.append(("backup_failed", "Today's backup did not complete. Your notes are safe on your computer, "
                                       "but there is no fresh copy."))
    if any(p.startswith("data: failed") for p in parts):
        found.append(("data_failed", "Your latest notes could not be copied to GitHub. They are safe on your computer "
                                     "and it will try again automatically."))
    due = []
    for kind, text in found:
        sent = state.get(f"alert_{kind}")
        try:
            recent = sent is not None and (now.date() - date.fromisoformat(sent)).days < ALERT_GAP_DAYS.get(kind, 1)
        except ValueError:
            recent = False
        if not recent:
            due.append((kind, text))
    return due


async def _send_alerts(app: Application) -> None:
    d = app.bot_data
    state_path = d["state_path"]
    now = d["now"]()
    for kind, text in due_alerts(now, load_state(state_path), Path(state_path).parent / "sync.log"):
        await app.bot.send_message(chat_id=d["owner_id"], text=text)
        state = load_state(state_path)
        state[f"alert_{kind}"] = now.date().isoformat()
        save_state(state_path, state)


async def _scheduler(app: Application) -> None:
    d = app.bot_data

    async def send(name: str, brief: Brief) -> None:
        mentor = d.get("mentor")
        if mentor is not None:
            try:
                if name == "morning":
                    extra = await asyncio.to_thread(mentor.morning_text, d["now"]())
                    if extra:
                        brief = Brief(text=brief.text + "\n\n" + extra, action_id=brief.action_id, ids=brief.ids,
                                      buttons=brief.buttons)
                elif name == "evening":
                    extra = await asyncio.to_thread(mentor.evening_text, d["now"]())
                    if extra:
                        brief = Brief(text=extra)
            except Exception as e:  # the plain brief still goes out
                log.warning("mentor %s part failed: %s", name, type(e).__name__)
        if brief.ids:
            _remember_ids(d, brief.ids)
        await app.bot.send_message(chat_id=d["owner_id"], text=brief.text, reply_markup=_markup(brief))

    async def mentor_tick() -> None:
        mentor = d.get("mentor")
        if mentor is None or not mentor.onboarding_due(d["now"]()):
            return
        text = await asyncio.to_thread(mentor.start_onboarding, d["now"]())
        await app.bot.send_message(chat_id=d["owner_id"], text=text)

    while True:
        try:
            await run_due_jobs(send, d["store"], d.get("goals_text", ""), d["now"](), d["state_path"], d.get("focus_projects"))
        except Exception as e:
            log.warning("scheduler: due jobs failed: %s", redact(str(e), d.get("token", "")))
        for step in (lambda: _send_alerts(app), mentor_tick):  # one failing step must not block the other
            try:
                await step()
            except Exception as e:
                log.warning("scheduler step failed: %s", redact(str(e), d.get("token", "")))
        await asyncio.sleep(SCHEDULER_INTERVAL_SECONDS)


MENU_COMMANDS = [
    ("brief", "today's plan"), ("todo", "put a task on your list"),
    ("book", "log what you read and learned"), ("done", "log a finished thing, or /done 2"), ("skip", "drop a brief item: /skip 2"),
    ("ask", "personal advice from Claude"), ("private", "save something Claude never sees"),
    ("summary", "how it all works"), ("usage", "what Claude calls cost you"),
]


async def _post_init(app: Application) -> None:
    try:
        await app.bot.set_my_commands(MENU_COMMANDS)
    except TelegramError as e:
        log.warning("could not set the command menu: %s", type(e).__name__)
    app.bot_data["scheduler_task"] = asyncio.create_task(_scheduler(app))


async def _post_shutdown(app: Application) -> None:
    task = app.bot_data.get("scheduler_task")
    if task:
        task.cancel()


def run_with_retries(
    run: Callable[[], None],
    token: str,
    sleep: Callable[[float], None] = time_module.sleep,
    initial_delay: float = 5,
    max_delay: float = 300,
) -> int:
    """Run the bot; if Telegram or the network is unavailable (e.g. Wi-Fi not up at logon), wait and retry.

    Returns 0 on a clean stop, 2 when Telegram rejects the token (retrying cannot help). The token is
    never logged. Ctrl+C / KeyboardInterrupt passes straight through.
    """
    delay = initial_delay
    while True:
        try:
            run()
            return 0
        except InvalidToken as e:
            log.error("Telegram rejected the bot token (%s); fix SB_TELEGRAM_TOKEN in .env", type(e).__name__)
            return 2
        except Exception as e:  # ANY crash: restart, never vanish silently (pythonw has no console)
            log.warning("bot stopped (%s): %s; retrying in %ss", type(e).__name__, redact(str(e), token), delay)
            sleep(delay)
            delay = min(delay * 2, max_delay)


# --- wiring --------------------------------------------------------------------------------------

def build_application(
    token: str,
    owner_id: int,
    store: Store,
    goals_text: str,
    state_path: Path,
    now: Callable[[], datetime] | None = None,
    focus_projects: tuple[str, ...] | None = None,
    classifier: Callable[[str], tuple[str, str]] | None = None,
    index=None,
    mentor=None,
) -> Application:
    if not token:
        raise ValueError("a Telegram bot token is required")
    if not isinstance(owner_id, int) or isinstance(owner_id, bool):
        raise ValueError("an owner Telegram user id is required")

    app = (
        ApplicationBuilder()
        .token(token)
        .job_queue(None)  # we schedule ourselves; avoids the APScheduler extra
        .concurrent_updates(True)  # a slow /ask must not freeze buttons and other messages
        .connect_timeout(20).read_timeout(30).write_timeout(30).pool_timeout(30)  # shaky Wi-Fi: default is 5s
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    app.bot_data.update(
        token=token, owner_id=owner_id, store=store, goals_text=goals_text, state_path=Path(state_path),
        focus_projects=focus_projects, classifier=classifier, index=index, mentor=mentor,
        now=now or (lambda: datetime.now().astimezone()),
    )

    only_owner = filters.User(user_id=owner_id) & filters.ChatType.PRIVATE  # defence in depth: handlers re-check
    app.add_handler(CommandHandler(["start", "help"], cmd_start, filters=only_owner))
    app.add_handler(CommandHandler("brief", cmd_brief, filters=only_owner))
    app.add_handler(CommandHandler("summary", cmd_summary, filters=only_owner))
    app.add_handler(CommandHandler("ask", cmd_ask, filters=only_owner))
    app.add_handler(CommandHandler("usage", cmd_usage, filters=only_owner))
    for kind in CAPTURE_COMMANDS:
        if kind != "done":  # /done is registered below: it handles both "/done 2" and "/done <text>"
            app.add_handler(CommandHandler(kind, _capture_command(kind), filters=only_owner))
    for verb in ("done", "skip"):
        app.add_handler(CommandHandler(verb, _mark_command(verb), filters=only_owner))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & only_owner, on_text))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_error_handler(_on_error)
    return app
