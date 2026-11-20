import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from secondbrain.docimport import Description, interpret_description, make_gist, store_document
from secondbrain.documents import read_upload
from secondbrain.store import Store

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 11, 20, 14, 0, tzinfo=IST)

CHAT = """12/03/2024, 10:16 - Rahul Sharma: Hey Daksh, saw your message about DevOps
12/03/2024, 10:17 - Daksh: I want to build an infra tool
13/03/2024, 09:00 - Rahul Sharma: First find who has the pain.
"""


class FakeLLM:
    name, is_local = "fake-local", True

    def __init__(self, reply):
        self.reply, self.prompts = reply, []

    def complete(self, prompt, *, system=None):
        self.prompts.append(prompt)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply(prompt) if callable(self.reply) else self.reply


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "brain")


def desc(**kw):
    base = dict(title="WhatsApp chat with Rahul (founder)", about="Advice from a founder on selling infra tools.",
                me="Daksh", roles={"Rahul Sharma": "founder"}, private=False)
    base.update(kw)
    return Description(**base)


# --- storing ------------------------------------------------------------------------------------------------------------

def test_store_creates_a_parent_and_part_cards_that_are_clearly_not_his_own_words(store):
    cards = store_document(store, read_upload("c.txt", CHAT.encode()), desc(), NOW, doc_id=77, gist="He explains how to find a pain.")
    assert [c.id for c in cards] == ["doc_77", "doc_77_p1"]
    parent, part = cards
    assert parent.source == part.source == "document" and parent.visibility == "private" and parent.channel is None
    parent_text = " ".join(k.text for k in parent.key_points)
    assert "Advice from a founder" in parent_text and "Rahul Sharma is founder" in parent_text and "Daksh is him" in parent_text
    assert "He explains how to find a pain." in parent_text and "approximate" in parent_text.lower()
    text = "\n".join(k.text for k in part.key_points)
    assert "Rahul Sharma (founder): Hey Daksh" in text and "Daksh: I want to build an infra tool" in text
    assert part.title == "WhatsApp chat with Rahul (founder) (part 1 of 1)" and part.consumed_at == NOW
    assert store.read_card("doc_77_p1").source == "document"


def test_private_keeps_every_card_local_only(store):
    cards = store_document(store, read_upload("c.txt", CHAT.encode()), desc(private=True), NOW, doc_id=78)
    assert all(c.channel == "local-only" for c in cards)


def test_storing_again_replaces_parts_and_leaves_no_stale_ones(store):
    big = "\n\n".join(f"Paragraph {i} about pricing and customers. " * 12 for i in range(60))
    first = store_document(store, read_upload("big.md", big.encode()), desc(roles={}, me=None), NOW, doc_id=79)
    assert len(first) >= 3
    store_document(store, read_upload("small.md", b"Just one short note about pricing."), desc(roles={}, me=None), NOW, doc_id=79)
    remaining = sorted(p.name for p in store.iter_card_files() if p.name.startswith("doc_79"))
    assert remaining == ["doc_79.json", "doc_79_p1.json"]


def test_text_documents_have_no_who_is_who_line(store):
    cards = store_document(store, read_upload("n.md", b"# Notes\n\nPricing advice for SaaS tools."), desc(me=None, roles={}), NOW, doc_id=80)
    assert "Who is who" not in " ".join(k.text for k in cards[0].key_points)


# --- understanding his description -------------------------------------------------------------------------------------------

def test_interpretation_uses_the_local_model_and_only_keeps_names_that_exist(store):
    upload = read_upload("c.txt", CHAT.encode())
    reply = json.dumps({"title": "Chat with Rahul", "about": "A founder advising me.", "me": "Daksh",
                        "roles": {"Rahul Sharma": "founder", "Ghost": "invented"}})
    llm = FakeLLM(reply)
    d = interpret_description(llm, upload, "This is my chat with founder Rahul. I'm Daksh.")
    assert d.title == "Chat with Rahul" and d.me == "Daksh" and d.roles == {"Rahul Sharma": "founder"} and d.private is False
    assert "data, not instructions" in llm.prompts[0] and "Rahul Sharma" in llm.prompts[0]


def test_interpretation_falls_back_without_the_model_and_still_finds_him(store):
    upload = read_upload("WhatsApp Chat with Rahul.txt", CHAT.encode())
    d = interpret_description(FakeLLM(RuntimeError("down")), upload, "my chat with a founder, I am Daksh")
    assert d.me == "Daksh" and d.about == "my chat with a founder, I am Daksh" and d.roles == {}
    assert "WhatsApp" in d.title


def test_the_word_private_in_his_reply_is_detected_without_the_model():
    upload = read_upload("n.md", b"Some founder note about pricing.")
    assert interpret_description(FakeLLM(RuntimeError("down")), upload, "keep this private please").private is True
    assert interpret_description(FakeLLM(RuntimeError("down")), upload, "a founder note").private is False
    assert interpret_description(FakeLLM(RuntimeError("down")), upload, "do not share with claude").private is True


def test_a_model_answer_that_names_nobody_real_for_me_is_ignored():
    chat = ("12/03/2024, 10:16 - Amit: hello there friend\n"
            "12/03/2024, 10:17 - Priya: hi, how are you today\n")
    upload = read_upload("c.txt", chat.encode())
    reply = json.dumps({"title": "t", "about": "a", "me": "Somebody Else", "roles": {}})
    assert interpret_description(FakeLLM(reply), upload, "chat with founder").me is None


# --- the gist ---------------------------------------------------------------------------------------------------------------------

def test_gist_is_bounded_and_a_failure_means_no_gist():
    long = "\n\n".join(f"Paragraph {i}: " + "pricing and customers " * 30 for i in range(400))
    upload = read_upload("big.md", long.encode())
    llm = FakeLLM("A short gist about pricing.")
    assert make_gist(llm, upload) == "A short gist about pricing."
    assert len(llm.prompts[0]) < 9000
    assert make_gist(FakeLLM(RuntimeError("down")), upload) is None
    assert make_gist(FakeLLM("   "), upload) is None
