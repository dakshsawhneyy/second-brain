import json
from datetime import datetime, timezone

import pytest

from secondbrain.adapters.takeout import WatchItem
from secondbrain.extract import Extraction, extract
from secondbrain.llm import LLMOutputError
from secondbrain.transcripts import Segment, Transcript

ITEM = WatchItem(video_id="aaaaaaaaaaa", title="Pricing for SaaS", url="https://www.youtube.com/watch?v=aaaaaaaaaaa",
                 channel="Founder Chan", watched_at=datetime(2026, 11, 17, tzinfo=timezone.utc))


class FakeProvider:
    name = "fake"
    is_local = True

    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts: list[str] = []

    def complete(self, prompt, *, system=None):
        self.prompts.append(prompt)
        return self.replies.pop(0)


def kp(text, topic="business/saas-pricing", t="01:00", confidence=0.8):
    return {"text": text, "topic": topic, "t": t, "confidence": confidence}


def reply(points, action=None) -> str:
    return json.dumps({"key_points": points, "action": action})


def transcript(n_segments=1, seg_chars=50) -> Transcript:
    return Transcript(video_id="aaaaaaaaaaa", language="en",
                      segments=[Segment(float(i * 30), "s" * seg_chars) for i in range(n_segments)])


def test_extract_single_chunk_basic():
    p = FakeProvider([reply([kp("Charge by outcome")], action="Write down your pricing metric")])
    r = extract(ITEM, transcript(), p)
    assert isinstance(r, Extraction)
    assert [k.text for k in r.key_points] == ["Charge by outcome"]
    assert r.key_points[0].topic == "business/saas-pricing" and r.key_points[0].t == "01:00"
    assert r.action is not None and r.action.text == "Write down your pricing metric" and r.action.status == "open"


def test_extract_merges_chunks_and_caps_at_seven_keeping_highest_confidence():
    t = transcript(n_segments=3, seg_chars=100)
    p = FakeProvider([
        reply([kp("a1", confidence=0.9), kp("a2", confidence=0.2), kp("a3", confidence=0.7)]),
        reply([kp("b1", confidence=0.95), kp("b2", confidence=0.1), kp("b3", confidence=0.6)]),
        reply([kp("c1", confidence=0.5), kp("c2", confidence=0.85), kp("c3", confidence=0.4)]),
    ])
    r = extract(ITEM, t, p, max_chars=120)
    assert len(p.prompts) == 3
    texts = [k.text for k in r.key_points]
    assert len(texts) == 7
    assert "a2" not in texts and "b2" not in texts  # the two lowest-confidence points were dropped
    assert texts == ["a1", "a3", "b1", "b3", "c1", "c2", "c3"]  # original order preserved


def test_extract_unknown_topic_becomes_uncertain():
    r = extract(ITEM, transcript(), FakeProvider([reply([kp("x", topic="ai/magic")])]))
    assert r.key_points[0].topic == "uncertain"


def test_extract_invalid_timestamp_becomes_none_and_long_form_kept():
    r = extract(ITEM, transcript(), FakeProvider([reply([kp("a", t="around 5 minutes"), kp("b", t="1:02:05"), kp("c", t=None)])]))
    assert [k.t for k in r.key_points] == [None, "1:02:05", None]


def test_extract_timestamp_whitespace_is_stripped():
    r = extract(ITEM, transcript(), FakeProvider([reply([kp("a", t=" 01:00 ")])]))
    assert r.key_points[0].t == "01:00"


def test_extract_empty_transcript_returns_nothing_without_llm_call():
    p = FakeProvider([])
    r = extract(ITEM, Transcript(video_id="aaaaaaaaaaa", language="en", segments=[]), p)
    assert r.key_points == [] and r.action is None
    assert p.prompts == []


def test_extract_llm_failure_raises_llm_output_error():
    with pytest.raises(LLMOutputError):
        extract(ITEM, transcript(), FakeProvider(["garbage", "garbage"]))


def test_extract_out_of_range_confidence_is_rejected():
    bad = reply([kp("x", confidence=1.7)])
    with pytest.raises(LLMOutputError):
        extract(ITEM, transcript(), FakeProvider([bad, bad]))


def test_extract_dedupes_identical_points_across_chunks():
    t = transcript(n_segments=2, seg_chars=100)
    p = FakeProvider([reply([kp("Same point")]), reply([kp("same point  ")])])
    r = extract(ITEM, t, p, max_chars=120)
    assert len(r.key_points) == 1


def test_extract_action_is_first_nonempty_and_blank_becomes_none():
    t = transcript(n_segments=2, seg_chars=100)
    r = extract(ITEM, t, FakeProvider([reply([kp("a")], action="  "), reply([kp("b")], action="Try it today")]), max_chars=120)
    assert r.action is not None and r.action.text == "Try it today"
    r2 = extract(ITEM, transcript(), FakeProvider([reply([kp("a")], action="   ")]))
    assert r2.action is None


def test_extract_action_text_is_bounded():
    r = extract(ITEM, transcript(), FakeProvider([reply([kp("a")], action="x" * 1000)]))
    assert r.action is not None and len(r.action.text) <= 300


def test_extract_prompt_has_metadata_transcript_and_untrusted_warning_but_no_personal_goals():
    p = FakeProvider([reply([kp("a")])])
    extract(ITEM, transcript(), p)
    prompt = p.prompts[0]
    assert "Pricing for SaaS" in prompt and "Founder Chan" in prompt and "[00:00]" in prompt
    assert "untrusted" in prompt.lower()
    assert "goal" not in prompt.lower()  # extraction may run on a cloud model: no personal context


def test_extract_ignores_points_with_empty_text():
    r = extract(ITEM, transcript(), FakeProvider([reply([kp("   "), kp("real")])]))
    assert [k.text for k in r.key_points] == ["real"]
