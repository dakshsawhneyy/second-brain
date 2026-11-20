from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from secondbrain.schema import Card, KeyPoint, Relevance, Tombstone, validate_topic, TOPICS, FORMATS, CARD_TYPES


def make_card(**over) -> Card:
    base = dict(
        id="yt_abc123",
        source="youtube",
        type="consumed",
        title="A video",
        consumed_at=datetime(2026, 11, 17, 10, 0, tzinfo=timezone.utc),
        topic={"primary": "infra/sre", "secondary": []},
    )
    base.update(over)
    return Card(**base)


def test_card_defaults_to_private_hot():
    c = make_card()
    assert c.visibility == "private"
    assert c.tier == "hot"
    assert c.schema_version == "card.v1"
    assert c.key_points == []


def test_validate_topic_unknown_returns_uncertain():
    assert validate_topic("ai/magic") == "uncertain"
    assert validate_topic("infra/sre") == "infra/sre"


def test_card_rejects_unknown_topic():
    with pytest.raises(ValidationError):
        make_card(topic={"primary": "ai/magic", "secondary": []})


def test_card_rejects_more_than_two_secondary_topics():
    with pytest.raises(ValidationError):
        make_card(topic={"primary": "infra/sre", "secondary": ["ai/agents", "ai/tools", "ai/news"]})


def test_relevance_rejects_score_over_100():
    with pytest.raises(ValidationError):
        Relevance(bet_job=5, bet_product=5, actionability=5, novelty=5, quality=5, score=101)


def test_relevance_rejects_subscore_over_10():
    with pytest.raises(ValidationError):
        Relevance(bet_job=11, bet_product=5, actionability=5, novelty=5, quality=5, score=50)


def test_confidence_rejects_above_one():
    with pytest.raises(ValidationError):
        KeyPoint(text="x", topic="ai/tools", t=None, confidence=1.5)


def test_key_point_rejects_unknown_topic():
    with pytest.raises(ValidationError):
        KeyPoint(text="x", topic="nope", t=None, confidence=0.5)


@pytest.mark.parametrize("bad_id", ["../evil", "a/b", "a b", "", "x" * 200, "a\\b"])
def test_card_rejects_unsafe_ids(bad_id):
    with pytest.raises(ValidationError):
        make_card(id=bad_id)


def test_card_rejects_unknown_type_and_visibility():
    with pytest.raises(ValidationError):
        make_card(type="gossip")
    with pytest.raises(ValidationError):
        make_card(visibility="public")


def test_extra_fields_are_forbidden():
    with pytest.raises(ValidationError):
        make_card(surprise="x")


def test_card_requires_timezone_aware_datetime():
    with pytest.raises(ValidationError):
        make_card(consumed_at=datetime(2026, 11, 17, 10, 0))


def test_taxonomy_constants_match_design():
    assert len(TOPICS) == 29  # 26 from the design + 3 work/* topics added 2026-11-19
    assert "noise/entertainment" in TOPICS and "uncertain" in TOPICS
    assert FORMATS == {"tip", "tutorial", "podcast", "talk", "news", "case-study", "opinion", "review"}
    assert {"consumed", "thought", "decided", "acted", "produced", "experiment", "friction", "book", "link", "commitment", "checkin"} == set(CARD_TYPES)


def test_tombstone_roundtrip():
    t = Tombstone(id="yt_x", source="youtube", title="t", url="https://youtu.be/x", date="2026-11-17", topic="noise/entertainment", score=10)
    assert Tombstone.model_validate_json(t.model_dump_json()) == t
