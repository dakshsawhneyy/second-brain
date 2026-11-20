from datetime import datetime, timezone

from secondbrain.chunks import CHUNK_MAX_CHARS, MAX_CHUNKS_PER_CARD, Chunk, chunk_card
from secondbrain.schema import Action, Card, KeyPoint, Topic

NOW = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)


def make(points=(), title="A title", action=None, reply_to=None, cid="c1"):
    return Card(id=cid, source="telegram", type="thought", title=title, consumed_at=NOW,
                topic=Topic(primary="uncertain"), reply_to=reply_to,
                key_points=[KeyPoint(text=p, topic="uncertain", confidence=1.0) for p in points],
                action=Action(text=action) if action else None)


def test_short_note_is_one_chunk():
    assert chunk_card(make(["hello world note"])) == [Chunk(id="c1#0", card_id="c1", ord=0, text="hello world note")]


def test_each_key_point_and_a_distinct_action_get_their_own_chunk():
    chunks = chunk_card(make(["first idea", "second idea"], action="do the third thing"))
    assert [c.text for c in chunks] == ["first idea", "second idea", "do the third thing"]
    assert [c.ord for c in chunks] == [0, 1, 2] and len({c.id for c in chunks}) == 3
    same = chunk_card(make(["email two recruiters"], action="email two recruiters"))
    assert [c.text for c in same] == ["email two recruiters"]  # an action that repeats the key point adds nothing


def test_long_key_point_splits_at_sentence_boundaries_under_the_limit():
    sentences = [f"This is sentence number {i} and it carries a fair amount of words to fill space." for i in range(16)]
    chunks = chunk_card(make([" ".join(sentences)]))
    assert len(chunks) >= 2 and all(len(c.text) <= CHUNK_MAX_CHARS for c in chunks)
    assert all(c.text.rstrip().endswith(".") for c in chunks)                      # split on a sentence end
    assert " ".join(c.text for c in chunks).split() == " ".join(sentences).split()  # nothing lost, nothing repeated


def test_unbroken_text_longer_than_the_limit_is_hard_split():
    chunks = chunk_card(make(["a" * 2000]))
    assert len(chunks) == 3 and all(len(c.text) <= CHUNK_MAX_CHARS for c in chunks)
    assert "".join(c.text for c in chunks) == "a" * 2000


def test_reply_context_is_part_of_chunk_zero_only():
    chunks = chunk_card(make(["yes", "and another point"], reply_to="Should I apply to remote jobs?"))
    assert chunks[0].text == "(in reply to: Should I apply to remote jobs?) yes" and chunks[1].text == "and another point"


def test_title_only_card_is_one_chunk_and_a_card_with_no_text_has_none():
    assert [c.text for c in chunk_card(make([], title="Zero to One"))] == ["Zero to One"]
    assert chunk_card(make([], title="")) == []
    assert chunk_card(make(["   ", ""], title="  ")) == []


def test_fifty_thousand_char_note_is_bounded_and_does_not_crash():
    chunks = chunk_card(make(["word " * 10_000]))
    assert 0 < len(chunks) <= MAX_CHUNKS_PER_CARD and all(len(c.text) <= CHUNK_MAX_CHARS for c in chunks)
    huge = chunk_card(make(["word " * 100_000]))
    assert len(huge) == MAX_CHUNKS_PER_CARD  # capped, never unbounded


def test_emoji_and_non_latin_text_survive_chunking():
    chunks = chunk_card(make(["🙂🙂🙂", "मुझे आज बहुत कुछ सीखना है। यह दूसरा वाक्य है।"]))
    assert [c.text for c in chunks][0] == "🙂🙂🙂" and "मुझे" in chunks[1].text
