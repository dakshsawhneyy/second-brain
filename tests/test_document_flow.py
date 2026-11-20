import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from telegram import ForceReply

from secondbrain.bot.documents import on_document, replay_document
from secondbrain.docimport import PendingDocs
from secondbrain.inbox import Inbox
from secondbrain.store import Store

from test_bot_app import NOW, OWNER, make_ctx, make_update, run
from test_documents import ANDROID, zip_bytes
from test_docimport import FakeLLM
from test_bot_app import store  # noqa: F401  (fixture)


class Sent(SimpleNamespace):
    pass


class DocMessage:
    """A Telegram message that can carry a document and hands out message ids for what the bot sends."""

    def __init__(self, text=None, message_id=1000, document=None, caption=None, reply_to=None):
        self.text, self.message_id, self.document, self.caption = text, message_id, document, caption
        self.date, self.reply_to_message, self.quote = None, reply_to, None
        self.replies, self._next = [], message_id * 10

    async def reply_text(self, text, **kwargs):
        self._next += 1
        self.replies.append((text, kwargs))
        return Sent(message_id=self._next, text=text)


def doc_update(name, data, message_id=1000, caption=None, size=None):
    class File:
        async def download_as_bytearray(self):
            return bytearray(data)

    class Doc:
        file_id, file_name, file_size = "FILE", name, size if size is not None else len(data)

        async def get_file(self):
            return File()

    msg = DocMessage(message_id=message_id, document=Doc(), caption=caption)
    return SimpleNamespace(effective_user=SimpleNamespace(id=OWNER), effective_chat=SimpleNamespace(id=OWNER, type="private"),
                           message=msg, callback_query=None)


def reply_update(text, prompt_message_id, message_id=2000):
    target = SimpleNamespace(message_id=prompt_message_id, text="prompt", caption=None, from_user=SimpleNamespace(is_bot=True))
    msg = DocMessage(text=text, message_id=message_id, reply_to=target)
    return SimpleNamespace(effective_user=SimpleNamespace(id=OWNER), effective_chat=SimpleNamespace(id=OWNER, type="private"),
                           message=msg, callback_query=None)


INTERPRETATION = json.dumps({"title": "Chat with Rahul (founder)", "about": "A founder advising me on selling infra tools.",
                             "me": "Daksh", "roles": {"Rahul Sharma": "founder"}})


@pytest.fixture
def ctx(store, tmp_path):
    c = make_ctx(store)
    c.bot_data.update(pending_docs=PendingDocs(tmp_path / "raw"), inbox=Inbox(tmp_path / "inbox.json"),
                      doc_llm=FakeLLM(lambda prompt: INTERPRETATION if "AUTHORS" in prompt else "A founder explains how to find pain."))
    return c


def send_chat(ctx, name="WhatsApp Chat with Rahul.zip", message_id=1000, caption=None):
    data = zip_bytes({"WhatsApp Chat with Rahul.txt": ANDROID.encode()}) if name.endswith(".zip") else ANDROID.encode()
    u = doc_update(name, data, message_id, caption)
    run(on_document(u, ctx))
    return u


# --- receiving -------------------------------------------------------------------------------------------------------------

def test_a_whatsapp_zip_makes_the_bot_ask_what_it_is_and_nothing_is_stored_yet(ctx, store):
    u = send_chat(ctx)
    text, kwargs = u.message.replies[0]
    assert "WhatsApp chat" in text and "Rahul Sharma" in text and "Daksh" in text and "which one is you" in text.lower()
    assert "private" in text.lower() and isinstance(kwargs["reply_markup"], ForceReply)
    assert not list(store.iter_card_files())                                           # waits for his answer
    assert ctx.bot_data["pending_docs"].by_prompt(u.message._next) is not None          # remembered by the prompt's message id


def test_his_reply_to_that_question_stores_the_cards_and_confirms(ctx, store):
    u = send_chat(ctx)
    prompt_id = u.message._next
    r = reply_update("This is my chat with founder Rahul. I'm Daksh.", prompt_id)
    run(__import__("secondbrain.bot.app", fromlist=["on_text"]).on_text(r, ctx))
    ids = sorted(p.stem for p in store.iter_card_files())
    assert ids == ["doc_1000", "doc_1000_p1"]
    parts = " ".join(k.text for k in store.read_card("doc_1000_p1").key_points)
    assert "Rahul Sharma (founder): Hey Daksh" in parts and "Daksh: Hi!" in parts
    assert "Chat with Rahul (founder)" in r.message.replies[-1][0] and "separate" in r.message.replies[-1][0].lower()
    assert ctx.bot_data["pending_docs"].by_prompt(prompt_id) is None                    # nothing left waiting
    assert ctx.bot_data["inbox"].pending() == []


def test_a_caption_on_the_file_skips_the_question(ctx, store):
    u = send_chat(ctx, caption="chat with founder Rahul, I'm Daksh")
    assert sorted(p.stem for p in store.iter_card_files()) == ["doc_1000", "doc_1000_p1"]
    assert all("which one is you" not in t.lower() for t, _ in u.message.replies)


def test_the_word_private_keeps_everything_local_only(ctx, store):
    send_chat(ctx, caption="my chat with Rahul, keep this private")
    assert {store.read_card(p.stem).channel for p in store.iter_card_files()} == {"local-only"}


def test_private_confirmation_says_claude_never_sees_it(ctx, store):
    u = send_chat(ctx, caption="my chat with Rahul, keep this private")
    assert "never" in u.message.replies[-1][0].lower() and "claude" in u.message.replies[-1][0].lower()


def test_text_and_markdown_files_work_too(ctx, store):
    u = doc_update("advice.md", b"# Advice\n\nFind the pain before you build. Charge early for it.", message_id=1100,
                   caption="notes a mentor gave me on pricing")
    run(on_document(u, ctx))
    assert sorted(p.stem for p in store.iter_card_files()) == ["doc_1100", "doc_1100_p1"]
    assert "Who is who" not in " ".join(k.text for k in store.read_card("doc_1100").key_points)


# --- problems -------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("name,data,size,expect", [
    ("photo.jpg", b"\xff\xd8\xff", None, "unsupported"),
    ("broken.zip", b"not a zip", None, "not a valid"),
    ("huge.txt", b"x", 30 * 1024 * 1024, "too large"),
    ("empty.txt", b"   ", None, "empty"),
])
def test_files_that_cannot_be_used_get_a_plain_reason_and_nothing_is_stored(ctx, store, name, data, size, expect):
    u = doc_update(name, data, size=size)
    run(on_document(u, ctx))
    assert expect in u.message.replies[0][0].lower() and not list(store.iter_card_files())
    assert ctx.bot_data["inbox"].pending() == [] and ctx.bot_data["pending_docs"].by_prompt(u.message._next) is None


def test_a_reply_to_some_other_message_is_not_taken_as_a_description(ctx, store):
    from secondbrain.bot.app import on_text
    send_chat(ctx)
    r = reply_update("a normal note replying to something else entirely", prompt_message_id=424242)
    run(on_text(r, ctx))
    assert not any(p.stem.startswith("doc_") for p in store.iter_card_files())


def test_if_storing_fails_the_file_stays_pending_and_he_is_told(ctx, store, monkeypatch):
    import secondbrain.bot.documents as flow
    u = send_chat(ctx)
    monkeypatch.setattr(flow, "store_document", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk full")))
    r = reply_update("my chat with Rahul, I'm Daksh", u.message._next)
    run(__import__("secondbrain.bot.app", fromlist=["on_text"]).on_text(r, ctx))
    assert "could not save" in r.message.replies[-1][0].lower()
    assert ctx.bot_data["pending_docs"].by_prompt(u.message._next) is not None          # he can simply reply again


def test_documents_are_indexed_right_away(ctx, store, tmp_path):
    from secondbrain.embed import HashEmbedder
    from secondbrain.index import Index
    index = Index(tmp_path / "i.db", HashEmbedder())
    index.rebuild(store)
    ctx.bot_data["index"] = index
    send_chat(ctx, caption="chat with founder Rahul, I'm Daksh")
    hits = index.search("find who has the pain", k=5, sources=frozenset({"document"}))
    assert hits and all(h.source == "document" for h in hits) and any("who has the pain" in h.snippet for h in hits)


# --- surviving a crash ------------------------------------------------------------------------------------------------------------------

def test_a_document_that_was_not_processed_before_a_crash_is_picked_up_again(ctx, store, tmp_path):
    from secondbrain.bot.app import _record_inbound, _replay_inbox
    import time
    u = doc_update("WhatsApp Chat with Rahul.zip", zip_bytes({"WhatsApp Chat with Rahul.txt": ANDROID.encode()}), message_id=1500)
    run(_record_inbound(u, ctx))
    entry = ctx.bot_data["inbox"].pending()[0][1]
    assert entry["kind"] == "document" and entry["name"] == "WhatsApp Chat with Rahul.zip"
    data = zip_bytes({"WhatsApp Chat with Rahul.txt": ANDROID.encode()})

    class File:
        async def download_as_bytearray(self):
            return bytearray(data)

    sent = []

    async def send_message(**kw):
        sent.append(kw)
        return Sent(message_id=777)

    async def get_file(file_id):
        assert file_id == "FILE"
        return File()

    app = SimpleNamespace(bot=SimpleNamespace(send_message=send_message, get_file=get_file), bot_data=ctx.bot_data)
    inbox = ctx.bot_data["inbox"]
    raw = inbox._load()
    raw["1500"]["at"] = time.time() - 3600
    inbox._save(raw)
    run(_replay_inbox(app))
    assert "WhatsApp chat" in sent[0]["text"] and ctx.bot_data["pending_docs"].by_prompt(777) is not None
    assert inbox.pending() == []                                                         # handled: waits only for his reply


# --- pending state --------------------------------------------------------------------------------------------------------------------

def test_pending_documents_survive_a_restart(tmp_path):
    p = PendingDocs(tmp_path)
    p.add(5, {"name": "c.zip", "kind": "whatsapp"}, "12/03/2024, 10:16 - A: hi\n")
    p.set_prompt(5, 99)
    again = PendingDocs(tmp_path)
    doc_id, meta, text = again.by_prompt(99)
    assert doc_id == 5 and meta["name"] == "c.zip" and text.startswith("12/03/2024")
    again.remove(5)
    assert PendingDocs(tmp_path).by_prompt(99) is None and not list((tmp_path / "pending_docs").glob("*"))


def test_a_voice_reply_works_like_a_typed_reply(ctx, store):
    from secondbrain.bot.app import _process_text
    u = send_chat(ctx)
    r = reply_update("ignored", u.message._next)
    run(_process_text(r, ctx.bot_data, "chat with founder Rahul, I am Daksh", strict_mentor=True))   # what on_voice calls
    assert store.has("doc_1000_p1")


def test_a_pdf_gets_the_same_question_with_its_page_count(ctx, store):
    from test_documents import make_pdf
    u = doc_update("pricing.pdf", make_pdf(["Charge early for the result", "Find the pain first"]), message_id=1300)
    run(on_document(u, ctx))
    text = u.message.replies[0][0]
    assert "pdf file" in text and "2 pages" in text and "why are you sharing it" in text
