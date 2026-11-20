"""Regression tests from the real conversation of 2026-11-20: the bot lost the thread, truncated pasted chats, searched
vague follow-ups blindly, and read a WhatsApp chat with the speakers swapped."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from secondbrain.advisor import PACK_CHARS, build_context
from secondbrain.docimport import Description, interpret_description, make_gist, store_document
from secondbrain.documents import looks_like_pasted_chat, read_upload
from secondbrain.embed import HashEmbedder
from secondbrain.index import Index
from secondbrain.retrieval import retrieve
from secondbrain.schema import Card, KeyPoint, Topic
from secondbrain.store import Store

from test_docimport import FakeLLM

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 11, 20, 21, 0, tzinfo=IST)


def note(cid, text, source="telegram", ctype="thought", hours_ago=3.0, channel=None, title=None):
    return Card(id=cid, source=source, type=ctype, title=title or text[:50], consumed_at=NOW - timedelta(hours=hours_ago),
                topic=Topic(primary="uncertain"), channel=channel,
                key_points=[KeyPoint(text=text, topic="uncertain", confidence=1.0)])


def exchange(cid, question, answer, hours_ago):
    return Card(id=cid, source="advice", type="thought", title=question[:60], consumed_at=NOW - timedelta(hours=hours_ago),
                topic=Topic(primary="uncertain"),
                key_points=[KeyPoint(text=f"Q: {question}", topic="uncertain", confidence=1.0),
                            KeyPoint(text=f"A: {answer}", topic="uncertain", confidence=1.0)])


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "brain")


# --- the conversation so far ----------------------------------------------------------------------------------------------

def test_the_newest_exchange_is_always_kept_and_the_oldest_are_dropped_first(store):
    for i in range(7):
        store.write_card(exchange(f"adv_{i}", f"question number {i} " + "q" * 300, f"answer number {i} " + "a" * 800 + f" END{i}",
                                  hours_ago=10 - i))
    pack = build_context(store, "what now", "goals", NOW)
    assert "END6" in pack and "END5" in pack                                   # the latest ones, whole
    assert "END0" not in pack                                                  # the oldest fell off first
    header = next(l for l in pack.splitlines() if l.startswith("THE CONVERSATION SO FAR"))
    assert "last exchange" in header.lower() and "not facts about him" in header.lower()


def test_exchanges_are_no_longer_cut_to_500_characters(store):
    answer = "A" * 850 + " THE-END"
    store.write_card(exchange("adv_1", "a question about pay", answer, hours_ago=1))
    assert "THE-END" in build_context(store, "and then?", "goals", NOW)


# --- long recent messages (pasted chats) ----------------------------------------------------------------------------------------

LINKEDIN = ("Yeshwant Maheshram sent the following message at 11:43 AM View Yeshwant's profile Yeshwant Maheshram 11:43 AM "
            "Hi Daksh, thanks for accepting my request! Founding Trainer role at ITFocus. " * 2 +
            "Daksh Sawhney sent the following message at 11:50 AM View Daksh's profile Daksh Sawhney 11:50 AM Thanks, tell me more. "
            "Yeshwant Maheshram sent the following message at 11:53 PM minimum Rs 3000 for the course, keep it realistic. " * 12)


def test_pasted_chat_detection():
    assert looks_like_pasted_chat(LINKEDIN) is True
    whatsapp = "\n".join(f"12/03/2024, 10:{i:02d} - Rahul: message number {i} about pricing and customers here" for i in range(10))
    assert looks_like_pasted_chat(whatsapp) is True
    assert looks_like_pasted_chat("Today I woke up early and thought about my plans. " * 30) is False
    assert looks_like_pasted_chat("short") is False


def test_the_newest_long_messages_keep_up_to_a_thousand_characters_and_are_labelled_as_pasted_conversations(store):
    store.write_card(note("tg_chat", LINKEDIN, hours_ago=1))
    store.write_card(note("tg_old1", "an older note " + "x" * 600, hours_ago=30))
    pack = build_context(store, "what do you think", "goals", NOW)
    recent = pack.split("RECENT ENTRIES")[1].split("EVIDENCE FROM HIS NOTES")[0]
    assert "pasted conversation" in recent.lower() and "not his own words" in recent.lower()
    assert "Rs 3000" in recent or "Founding Trainer" in recent
    chat_line = next(l for l in recent.splitlines() if "pasted conversation" in l.lower())
    assert 700 < len(chat_line) <= 1250                                         # was 260
    older = next(l for l in recent.splitlines() if "older note" in l)
    assert len(older) <= 330                                                    # older ones stay short


# --- vague follow-ups ------------------------------------------------------------------------------------------------------------

def library_with_a_shared_chat(tmp_path):
    store = Store(tmp_path / "brain")
    store.write_card(exchange("adv_1", "I asked Yeshwant about the pay structure, should I take the ITFocus opportunity?",
                              "I cannot say yet; get the terms in writing.", hours_ago=2))
    store.write_card(note("doc_7_p1", "Yeshwant: Minimum Rs 3000 per session for the Founding Trainer course on ITFocus, keep it realistic",
                          source="document", hours_ago=5, title="Chat with Yeshwant (part 1 of 1)"))
    store.write_card(note("tg_junk", "my daily routine and distractions and sleep", hours_ago=40))
    index = Index(tmp_path / "i.db", HashEmbedder())
    index.rebuild(store)
    return store, index


def test_a_vague_follow_up_finds_the_shared_chat_through_the_last_exchange(tmp_path):
    store, index = library_with_a_shared_chat(tmp_path)
    pack = build_context(store, "hope that makes sense now for your previous message", "goals", NOW, index=index)
    assert "Minimum Rs 3000 per session" in pack.split("MATERIAL HE SHARED")[1]


def test_a_clear_standalone_question_does_not_get_the_extra_conversation_queries(tmp_path):
    store, index = library_with_a_shared_chat(tmp_path)
    calls = []
    real = index.search

    def spy(query, **kw):
        calls.append(query)
        return real(query, **kw)

    index.search = spy
    build_context(store, "What are the main ways a bootstrapped infrastructure founder can find paying customers in India quickly?",
                  "goals", NOW, index=index)
    assert len(set(calls)) <= 2                                                 # evidence + material only, no follow-up queries


def test_retrieve_fuses_extra_queries(tmp_path):
    class FakeIndex:
        def search(self, query, **kw):
            from secondbrain.index import Hit
            data = {"vague": [Hit("a", "t", "junk", 0.3, "2026-11-20", "telegram")],
                    "specific words": [Hit("b", "t", "the real answer", 0.8, "2026-11-20", "telegram")]}
            return data.get(query, [])

    result = retrieve(FakeIndex(), "vague", k=5, extra_queries=["specific words"])
    assert {e.card_id for e in result.items} == {"a", "b"}


# --- recently shared documents are always described -----------------------------------------------------------------------------------

def test_a_document_shared_today_is_always_introduced_even_when_the_search_finds_nothing(tmp_path):
    store = Store(tmp_path / "brain")
    parent = Card(id="doc_7", source="document", type="thought", title="Chat with Yeshwant", consumed_at=NOW - timedelta(hours=2),
                  topic=Topic(primary="uncertain"),
                  key_points=[KeyPoint(text="About this document (his description): a founder offering a trainer role",
                                       topic="uncertain", confidence=1.0),
                              KeyPoint(text="Who is who: Yeshwant is founder of ITFocus; Daksh is him.", topic="uncertain", confidence=1.0)])
    store.write_card(parent)
    store.write_card(note("tg_x", "completely unrelated note about sleep", hours_ago=50))
    pack = build_context(store, "zzzz qqqq", "goals", NOW)
    material = pack.split("MATERIAL HE SHARED")[1]
    assert "a founder offering a trainer role" in material and "Yeshwant is founder of ITFocus" in material


def test_an_old_document_is_not_forced_into_every_pack(tmp_path):
    store = Store(tmp_path / "brain")
    store.write_card(Card(id="doc_7", source="document", type="thought", title="Old chat", consumed_at=NOW - timedelta(days=10),
                          topic=Topic(primary="uncertain"),
                          key_points=[KeyPoint(text="About this document: old stuff", topic="uncertain", confidence=1.0)]))
    assert "MATERIAL HE SHARED" not in build_context(store, "zzzz qqqq", "goals", NOW)


def test_the_pack_stays_within_its_budget_in_the_worst_case(tmp_path):
    store = Store(tmp_path / "brain")
    for i in range(8):
        store.write_card(exchange(f"adv_{i}", "q" * 900, "a" * 1500, hours_ago=20 - i))
        store.write_card(note(f"tg_{i}", LINKEDIN, hours_ago=5 + i))
        store.write_card(note(f"doc_{i}_p1", "Rahul (founder): pricing advice " * 40, source="document", hours_ago=3))
    index = Index(tmp_path / "i.db", HashEmbedder())
    index.rebuild(store)
    pack = build_context(store, "pricing advice", "g" * 5000, NOW, index=index, profile="p" * 9000)
    assert len(pack) <= PACK_CHARS and "EVIDENCE FROM HIS NOTES" in pack and "THE CONVERSATION SO FAR" in pack


# --- WhatsApp speakers are never swapped again ---------------------------------------------------------------------------------------

CHAT = """12/03/2024, 10:16 - Yeshwant ITFocus: Hi, we can talk at 6 pm
12/03/2024, 10:17 - You: ok, I am at the barber so 6 is better
13/03/2024, 09:00 - Yeshwant ITFocus: Minimum Rs 3000 for the course
"""


def test_the_author_called_you_is_him_even_if_the_model_says_otherwise():
    upload = read_upload("chat.txt", CHAT.encode())
    wrong = json.dumps({"title": "Chat", "about": "a founder", "me": "Yeshwant ITFocus",
                        "roles": {"Yeshwant ITFocus": "Founder", "You": "Bot"}})
    d = interpret_description(FakeLLM(wrong), upload, "this is the chat with Yeshwant about the trainer role")
    assert d.me == "You" and "You" not in d.roles and d.roles == {"Yeshwant ITFocus": "Founder"}


def test_an_author_with_his_own_name_is_him_and_the_model_cannot_override(tmp_path):
    chat = CHAT.replace("You:", "Daksh Sawhney:")
    wrong = json.dumps({"title": "Chat", "about": "x", "me": "Yeshwant ITFocus", "roles": {}})
    d = interpret_description(FakeLLM(wrong), read_upload("c.txt", chat.encode()), "chat with a founder")
    assert d.me == "Daksh Sawhney"


def test_labels_put_him_as_daksh_and_the_others_by_name_with_role(store):
    upload = read_upload("chat.txt", CHAT.encode())
    desc = Description(title="Chat with Yeshwant", about="x", me="You", roles={"Yeshwant ITFocus": "Founder"})
    cards = store_document(store, upload, desc, NOW, doc_id=5)
    text = "\n".join(k.text for k in cards[1].key_points)
    assert "Yeshwant ITFocus (Founder): Hi, we can talk at 6 pm" in text and "Daksh: ok, I am at the barber" in text
    assert "You:" not in text and "(Bot)" not in text
    assert "Daksh is him" in " ".join(k.text for k in cards[0].key_points)


def test_when_nobody_can_be_identified_the_labels_stay_neutral_and_no_one_is_claimed_as_him(store):
    chat = CHAT.replace("Yeshwant ITFocus", "Amit").replace("You", "Priya")
    upload = read_upload("chat.txt", chat.encode())
    d = interpret_description(FakeLLM(RuntimeError("down")), upload, "a chat with two people")
    assert d.me is None
    cards = store_document(store, upload, d, NOW, doc_id=6)
    parent = " ".join(k.text for k in cards[0].key_points)
    assert "is him" not in parent and "Amit: Hi" in "\n".join(k.text for k in cards[1].key_points)


def test_the_gist_is_made_from_the_messages_not_the_whatsapp_banner():
    text = ("12/03/2024, 10:15 - Messages and calls are end-to-end encrypted. No one outside of this chat can read them.\n" + CHAT)
    upload = read_upload("chat.txt", text.encode())
    llm = FakeLLM("A founder offers a trainer role.")
    assert make_gist(llm, upload) == "A founder offers a trainer role."
    assert "end-to-end encrypted" not in llm.prompts[0] and "Minimum Rs 3000" in llm.prompts[0]
    assert "Yeshwant ITFocus:" in llm.prompts[0]                               # authors kept, so the gist knows who said what


def test_the_extracted_text_of_a_saved_document_is_kept_locally_for_reprocessing(tmp_path):
    from secondbrain.docimport import PendingDocs
    p = PendingDocs(tmp_path)
    p.add(5, {"name": "c.txt", "kind": "whatsapp"}, "12/03/2024, 10:16 - A: hi\n")
    p.set_prompt(5, 9)
    p.mark_saved(5, ["doc_5", "doc_5_p1"])
    assert (tmp_path / "pending_docs" / "5.txt").read_text(encoding="utf-8").startswith("12/03/2024")
    assert p.saved_by_prompt(9) == (5, ["doc_5", "doc_5_p1"])
