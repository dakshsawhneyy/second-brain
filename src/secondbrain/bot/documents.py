"""Telegram side of sharing documents: receive the file, ask what it is, store it when he answers, survive crashes.

A file is parsed locally and held as "pending" (on disk) until he replies to the bot's question. His reply, typed or spoken, is
the description. A caption on the file skips the question. Nothing is ever lost silently: the message stays in the durable
inbox until the question has been sent (or the file stored), a reply is recorded for the document (never as a plain note), a
file that cannot be read gets a reply, and a saved document can still be made private afterwards.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from telegram import ForceReply, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from ..docimport import _PRIVATE, interpret_description, make_gist, store_document
from ..documents import MAX_UPLOAD_BYTES, DocumentError, Upload, parse_whatsapp, read_upload

log = logging.getLogger("secondbrain.bot")
BIG_TEXT_CHARS = 30_000  # beyond this the local model takes a while: say so
PARSE_TIMEOUT = 90.0  # seconds: a file that takes longer to read than this is skipped (and he is told)
PLACEHOLDER = "What is it? Who is who? (add 'private' to keep it from Claude)"
DATA_REPO_NOTE = "It is still copied to your private data repo on GitHub like all your notes."


def _inbox_done(d, mid) -> None:
    inbox = d.get("inbox")
    if inbox is not None and mid is not None:
        try:
            inbox.done(mid)
        except Exception as e:  # bookkeeping must never break a message
            log.warning("inbox cleanup failed: %s", type(e).__name__)


def _lock(d, doc_id: int) -> asyncio.Lock:
    """One lock per document: two quick replies to the same question are handled one after the other, never at once."""
    return d.setdefault("doc_locks", {}).setdefault(doc_id, asyncio.Lock())


def _range(upload: Upload) -> str:
    days = sorted(m.when for m in upload.messages if m.when)
    if not days:
        return ""
    first, last = days[0], days[-1]
    return f"{first.day} {first:%b %Y} to {last.day} {last:%b %Y}"


def _prompt_text(upload: Upload) -> str:
    if upload.kind == "whatsapp":
        authors = list(dict.fromkeys(m.author for m in upload.messages))
        names = ", ".join(authors[:6]) + (" and others" if len(authors) > 6 else "")
        span = f" ({_range(upload)})" if _range(upload) else ""
        return (f"Got {upload.name}: a WhatsApp chat, {len(upload.messages)} messages between {names}{span}. "
                "What is this chat, and which one is you? Reply to this message in your own words. "
                "Add the word private to keep it away from Claude.")
    words = len(upload.text.split())
    size = f"{upload.pages} pages, about {words} words" if upload.kind == "pdf" else f"about {words} words"
    return (f"Got {upload.name}: a {upload.kind} file, {size}. What is it, and why are you sharing it? "
            "Reply to this message in your own words. Add the word private to keep it away from Claude.")


async def _ask(d, send, doc_id: int, text: str) -> bool:
    """Send the question (with a reply box) and remember which file it belongs to. False if it could not be sent."""
    try:
        sent = await send(text, reply_markup=ForceReply(input_field_placeholder=PLACEHOLDER))
    except Exception as e:
        log.warning("could not send the question about a shared file: %s", type(e).__name__)
        return False
    d["pending_docs"].set_prompt(doc_id, sent.message_id)
    return True


async def intake(d, send, *, name: str, size: int | None, get_bytes, caption: str, doc_id: int) -> None:
    """Read a shared file and either store it (when a caption describes it) or ask him what it is."""
    if size and size > MAX_UPLOAD_BYTES:
        _inbox_done(d, doc_id)
        await send("I can't use that file: that file is too large (the limit is 20 MB). For a WhatsApp chat, export it without media.")
        return
    try:
        data = await get_bytes()
    except Exception as e:  # network trouble: it stays in the inbox and is retried automatically
        log.warning("could not download a shared file: %s", type(e).__name__)
        try:
            await send("I couldn't download that file right now. I have kept it and will try again automatically.")
        except Exception:
            pass
        return
    try:
        upload = await asyncio.wait_for(asyncio.to_thread(read_upload, name, data), PARSE_TIMEOUT)
    except DocumentError as e:
        _inbox_done(d, doc_id)
        await send(f"I can't use that file: {e}.")
        return
    except asyncio.TimeoutError:
        _inbox_done(d, doc_id)
        await send("I can't use that file: it took too long to read, so I skipped it.")
        return
    except Exception as e:  # a hostile or odd file must never leave him without an answer or retry forever
        log.warning("could not read a shared file: %s", type(e).__name__)
        _inbox_done(d, doc_id)
        await send("I can't use that file: it could not be read.")
        return
    pending = d["pending_docs"]
    pending.add(doc_id, {"name": upload.name, "kind": upload.kind}, upload.text)
    if caption and caption.strip():
        status = await finish(d, send, doc_id, caption)
        if status == "failed":  # saving failed: leave him a question he can answer to try again
            if not await _ask(d, send, doc_id, "I could not save that file just now. Reply to this message and I will try again."):
                return  # nothing to reply to yet: the inbox entry stays, so it is asked again later
        _inbox_done(d, doc_id)
        return
    if await _ask(d, send, doc_id, _prompt_text(upload)):
        _inbox_done(d, doc_id)  # only now is it safe to forget the message: the question is out and remembered


async def finish(d, send, doc_id: int, description: str) -> str:
    """Store a pending document using his description. Returns "saved", "failed" (still pending, he can reply again) or
    "missing" (no such pending file, e.g. a concurrent reply already stored it)."""
    async with _lock(d, doc_id):
        pending = d["pending_docs"]
        loaded = pending.get(doc_id)
        if loaded is None:
            return "missing"
        meta, text = loaded
        upload = Upload(meta["kind"], meta["name"], text, parse_whatsapp(text) if meta["kind"] == "whatsapp" else [])
        llm, store, index = d.get("doc_llm"), d["store"], d.get("index")
        now: datetime = d["now"]()
        if len(text) > BIG_TEXT_CHARS:
            await send("Reading it carefully, this can take a few minutes...")

        def work():
            desc = interpret_description(llm, upload, description, tuple(d.get("owner_names") or ("daksh",)))
            gist = make_gist(llm, upload)
            return desc, store_document(store, upload, desc, now, doc_id, gist)

        try:
            desc, cards = await asyncio.to_thread(work)
        except Exception as e:
            log.warning("could not store a shared document: %s", type(e).__name__)
            await send("I could not save that file right now. It is kept, so just reply again in a moment.")
            return "failed"
        if index is not None:
            for card in cards:
                try:
                    await asyncio.to_thread(index.add_card, card)
                except Exception as e:  # the next sync will index it
                    log.warning("could not index %s now: %s", card.id, type(e).__name__)
        pending.mark_saved(doc_id, [c.id for c in cards])
        parts = len(cards) - 1
        where = f"{parts} part{'s' if parts != 1 else ''}"
        if desc.private or cards[0].channel == "local-only":
            await send(f'Saved "{desc.title}" as private ({where}). Claude never sees it. {DATA_REPO_NOTE}')
        else:
            await send(f'Saved "{desc.title}" ({where}). I keep it separate from your own notes and use it when you ask me things.')
        return "saved"


async def make_private(d, send, doc_id: int, card_ids: list[str]) -> None:
    """A saved document becomes private afterwards: every card turns local-only and is re-indexed."""
    store, index = d["store"], d.get("index")
    title = "that file"
    changed = False
    for cid in card_ids:
        try:
            card = store.read_card(cid)
        except KeyError:
            continue
        if cid == f"doc_{doc_id}":
            title = card.title
        if card.channel != "local-only":
            card = card.model_copy(update={"channel": "local-only"})
            store.write_card(card)
            changed = True
            if index is not None:
                try:
                    await asyncio.to_thread(index.add_card, card)
                except Exception as e:
                    log.warning("could not re-index %s now: %s", cid, type(e).__name__)
    if changed:
        await send(f'Done: "{title}" is private now. Claude will not see it. {DATA_REPO_NOTE}')
    else:
        await send(f'"{title}" was already private. {DATA_REPO_NOTE}')


async def reply_core(d, send, prompt_id, text: str) -> bool:
    """Handle a message that answers the bot's question about a file. True if it was about a document, False if it was an
    ordinary message (e.g. a late reply that does not ask for privacy), which then continues as a normal note."""
    pending = d.get("pending_docs")
    if pending is None or prompt_id is None:
        return False
    found = pending.by_prompt(prompt_id)
    if found:
        if await finish(d, send, found[0], text) != "missing":
            return True
    saved = pending.saved_by_prompt(prompt_id)  # also reached when a concurrent reply stored it while this one waited
    if saved and _PRIVATE.search(text):
        await make_private(d, send, saved[0], saved[1])
        return True
    return False


async def handle_reply(update: Update, d, text: str) -> bool:
    target = getattr(update.message, "reply_to_message", None)
    if target is None:
        return False
    return await reply_core(d, update.message.reply_text, getattr(target, "message_id", None), text)


async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    d = context.bot_data
    message = update.message
    user, chat = update.effective_user, update.effective_chat
    if message is None or getattr(message, "document", None) is None or user is None or chat is None:
        return
    if user.id != d.get("owner_id") or chat.type != "private" or d.get("pending_docs") is None:
        return
    doc, mid = message.document, message.message_id
    inflight = d.setdefault("inflight", set())
    inflight.add(mid)
    try:
        async def get_bytes() -> bytes:
            file = await doc.get_file()
            return bytes(await file.download_as_bytearray())

        await intake(d, message.reply_text, name=doc.file_name or "shared file", size=doc.file_size, get_bytes=get_bytes,
                     caption=message.caption or "", doc_id=mid)
    finally:
        inflight.discard(mid)


def _sender(app):
    d = app.bot_data

    async def send(text, **kwargs):
        return await app.bot.send_message(chat_id=d["owner_id"], text=text, **kwargs)

    return send


async def replay_document(app, mid: int, entry: dict) -> None:
    """Retry a shared file whose handling did not finish (crash, no network)."""
    async def get_bytes() -> bytes:
        file = await app.bot.get_file(entry["file_id"])
        return bytes(await file.download_as_bytearray())

    await intake(app.bot_data, _sender(app), name=entry.get("name") or "shared file", size=entry.get("size"), get_bytes=get_bytes,
                 caption=entry.get("caption") or "", doc_id=mid)


async def replay_docreply(app, entry: dict, text: str | None = None) -> bool:
    """Finish a document from a reply (typed, or the transcript of a spoken one) that was recorded before a crash.
    True if it was handled; False means it was an ordinary message and should be saved as a note."""
    return await reply_core(app.bot_data, _sender(app), entry.get("prompt_id", entry.get("docprompt")),
                            text if text is not None else entry.get("text", ""))
