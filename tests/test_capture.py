import re
from datetime import datetime, timezone

import pytest

from secondbrain.bot.capture import parse_capture

NOW = datetime(2026, 11, 17, 9, 30, tzinfo=timezone.utc)


@pytest.mark.parametrize("prefix,card_type", [
    ("idea", "thought"), ("friction", "friction"), ("experiment", "experiment"),
    ("decided", "decided"), ("done", "acted"), ("made", "produced"),
])
def test_each_prefix_sets_type_and_keeps_text(prefix, card_type):
    c = parse_capture(f"{prefix}: ship the brief first", NOW)
    assert c.type == card_type
    assert c.key_points[0].text == "ship the brief first"
    assert c.title == "ship the brief first"


def test_book_splits_idea_and_action():
    c = parse_capture("book: Zero to One | monopoly beats competition | pick a niche", NOW)
    assert c.type == "book" and c.title == "Zero to One"
    assert c.key_points[0].text == "monopoly beats competition"
    assert c.action is not None and c.action.text == "pick a niche" and c.action.status == "open"


def test_book_with_only_title_or_title_and_idea():
    only_title = parse_capture("book: Zero to One", NOW)
    assert only_title.title == "Zero to One" and only_title.key_points == [] and only_title.action is None
    with_idea = parse_capture("book: Zero to One | monopolies win", NOW)
    assert with_idea.key_points[0].text == "monopolies win" and with_idea.action is None


def test_url_only_is_link():
    c = parse_capture("  https://example.com/post?id=1  ", NOW)
    assert c.type == "link" and c.url == "https://example.com/post?id=1" and c.title == "https://example.com/post?id=1"


def test_url_with_extra_words_is_a_thought_not_a_link():
    c = parse_capture("read this https://example.com later", NOW)
    assert c.type == "thought" and c.url is None


def test_unprefixed_is_thought():
    c = parse_capture("I keep switching tasks every hour", NOW)
    assert c.type == "thought" and c.key_points[0].text == "I keep switching tasks every hour"


def test_always_private_telegram_uncertain_topic():
    c = parse_capture("idea: something personal", NOW)
    assert (c.visibility, c.source, c.topic.primary, c.tier) == ("private", "telegram", "uncertain", "hot")
    assert c.consumed_at == NOW


def test_prefix_is_case_and_space_insensitive():
    assert parse_capture("BOOK : X | y", NOW).type == "book"
    assert parse_capture("   Idea :   spaced out  ", NOW).key_points[0].text == "spaced out"


@pytest.mark.parametrize("text", ["", "   ", "\n", "idea:", "idea:   ", "book:", "done: "])
def test_empty_capture_raises_value_error(text):
    with pytest.raises(ValueError):
        parse_capture(text, NOW)


def test_id_format_and_determinism():
    a = parse_capture("idea: one", NOW)
    assert re.fullmatch(r"tg_\d+_[0-9a-f]{4}", a.id)
    assert parse_capture("idea: one", NOW).id == a.id
    assert parse_capture("idea: two", NOW).id != a.id
    later = datetime(2026, 11, 17, 9, 30, 1, tzinfo=timezone.utc)
    assert parse_capture("idea: one", later).id != a.id


def test_message_id_makes_the_card_id_stable_across_redelivery():
    later = datetime(2026, 11, 18, 8, 0, tzinfo=timezone.utc)
    a = parse_capture("idea: one", NOW, message_id=777)
    b = parse_capture("idea: one", later, message_id=777)
    assert a.id == b.id == "tg_777"
    assert parse_capture("idea: one", NOW, message_id=778).id == "tg_778"


def test_multiline_text_kept_in_key_point_but_title_is_flat_and_short():
    body = "first line\nsecond line " + "x" * 200
    c = parse_capture(f"idea: {body}", NOW)
    assert "\n" in c.key_points[0].text
    assert "\n" not in c.title and len(c.title) <= 80


def test_unicode_text_roundtrip():
    c = parse_capture("idea: हिंदी में सोचना 🚀", NOW)
    assert c.key_points[0].text == "हिंदी में सोचना 🚀"


def test_naive_datetime_is_rejected():
    with pytest.raises(ValueError):
        parse_capture("idea: x", datetime(2026, 11, 17, 9, 30))


def test_prefix_inside_text_is_not_treated_as_prefix():
    c = parse_capture("remember the idea: ship it", NOW)
    assert c.type == "thought" and c.key_points[0].text == "remember the idea: ship it"


def test_todo_prefix_creates_an_open_action_for_the_brief():
    c = parse_capture("todo: send 5 applications", NOW)
    assert c.type == "thought" and c.action is not None
    assert c.action.text == "send 5 applications" and c.action.status == "open"
