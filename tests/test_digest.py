import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pytest

from secondbrain.digest import (DigestRun, build_day_digest, build_month_digest, build_week_digest, refresh_digests,
                                update_living_profile)
from secondbrain.schema import Card, KeyPoint, Topic
from secondbrain.store import Store

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 11, 20, 12, 0, tzinfo=IST)
DAY = date(2026, 11, 18)


class FakeLLM:
    """reply(prompt) -> str. Records prompts."""
    name, is_local = "fake-local", True

    def __init__(self, reply=None):
        self.reply, self.prompts = reply, []

    def complete(self, prompt, *, system=None):
        self.prompts.append(prompt)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply(prompt) if callable(self.reply) else self.reply


def facts_reply(prompt):
    """A model that cites the first two note ids it sees in the prompt."""
    import re
    ids = re.findall(r"^\[([^\]]+)\]", prompt, flags=re.M)[:2]
    return json.dumps({"facts": [{"text": "He worked on his plan and felt unsure.", "from": ids}]})


def note(cid, text, day=DAY, source="telegram", channel=None, hour=10, ctype="thought"):
    when = datetime.combine(day, time(hour, 0), tzinfo=IST)
    return Card(id=cid, source=source, type=ctype, title=text[:50], consumed_at=when, topic=Topic(primary="uncertain"),
                channel=channel, key_points=[KeyPoint(text=text, topic="uncertain", confidence=1.0)],
                mentor={"day": day, "item": 1} if ctype in ("commitment", "checkin") else None)


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "brain")


def write_day(store, day=DAY, n=3, prefix="tg"):
    for i in range(n):
        store.write_card(note(f"{prefix}_{day:%d}_{i}", f"note {i} written on {day} about plans and worries", day=day, hour=9 + i))


# --- day digests ------------------------------------------------------------------------------------------------

def test_day_digest_cites_only_real_card_ids_and_drops_invented_ones(store):
    write_day(store)
    reply = json.dumps({"facts": [{"text": "He planned his week.", "from": ["tg_18_0", "tg_INVENTED"]},
                                  {"text": "A fact citing nothing real.", "from": ["tg_FAKE"]}]})
    card = build_day_digest(store, DAY, FakeLLM(reply), NOW)
    assert card.id == "dgd_20261118" and card.source == "digest" and card.visibility == "private"
    assert [k.text for k in card.key_points] == ["He planned his week. (from tg_18_0)"]  # invented id dropped, empty fact dropped
    assert set(card.derived_from) == {"tg_18_0", "tg_18_1", "tg_18_2"}                  # all inputs, for change detection
    assert card.consumed_at.astimezone(IST).date() == DAY and card.provenance.model == "fake-local"


def test_digest_excludes_local_only_session_ledger_advice_and_digest_cards(store):
    write_day(store, n=3)
    store.write_card(note("tg_secret", "my private fear about money", channel="local-only"))
    store.write_card(note("cc_1", "claude code session summary", source="claude-code"))
    store.write_card(note("mc_1", "a commitment", source="mentor", ctype="commitment"))
    store.write_card(note("adv_1", "Claude's earlier answer", source="advice"))
    store.write_card(note("dgd_x", "an older digest", source="digest"))
    llm = FakeLLM(facts_reply)
    card = build_day_digest(store, DAY, llm, NOW)
    assert set(card.derived_from) == {"tg_18_0", "tg_18_1", "tg_18_2"}
    prompt = llm.prompts[0]
    assert all(bad not in prompt for bad in ("private fear", "session summary", "a commitment", "earlier answer", "older digest"))


def test_session_summary_cards_never_feed_a_digest(store):
    for i in range(5):
        store.write_card(note(f"cc_{i}", f"session summary number {i} about refactoring", source="claude-code"))
    assert build_day_digest(store, DAY, FakeLLM(facts_reply), NOW) is None


def test_fewer_than_three_cards_makes_no_digest_and_no_model_call(store):
    write_day(store, n=2)
    llm = FakeLLM(facts_reply)
    assert build_day_digest(store, DAY, llm, NOW) is None and llm.prompts == []


def test_llm_failure_or_garbage_keeps_the_previous_digest_and_returns_none(store):
    write_day(store)
    first = build_day_digest(store, DAY, FakeLLM(facts_reply), NOW)
    store.write_card(first)
    write_day(store, n=4)  # the day changed
    assert build_day_digest(store, DAY, FakeLLM(RuntimeError("model down")), NOW) is None
    assert build_day_digest(store, DAY, FakeLLM("not json at all"), NOW) is None
    assert build_day_digest(store, DAY, FakeLLM(json.dumps({"facts": []})), NOW) is None
    assert store.read_card("dgd_20261118").derived_from == first.derived_from  # untouched


def test_model_input_is_bounded(store):
    for i in range(3):
        store.write_card(note(f"tg_big_{i}", "word " * 4000, hour=9 + i))
    llm = FakeLLM(facts_reply)
    build_day_digest(store, DAY, llm, NOW)
    assert len(llm.prompts[0]) < 9000


# --- refresh: only what changed, oldest first, bounded cost -------------------------------------------------------

def test_unchanged_day_is_not_regenerated_and_a_day_with_a_new_card_is(store):
    write_day(store)
    llm = FakeLLM(facts_reply)
    run = refresh_digests(store, llm, NOW)
    assert run == DigestRun(created=["dgd_20261118"], failed=0, skipped=0) and len(llm.prompts) == 1
    again = refresh_digests(store, llm, NOW)
    assert again.created == [] and again.skipped == 1 and len(llm.prompts) == 1       # nothing changed: no model call
    store.write_card(note("tg_late", "one more note that day about the plan", hour=20))
    assert refresh_digests(store, llm, NOW).created == ["dgd_20261118"] and len(llm.prompts) == 2


def test_refresh_skips_today_stops_at_max_calls_and_goes_oldest_first(store):
    for d in (date(2026, 11, 14), date(2026, 11, 15), date(2026, 11, 16), date(2026, 11, 20)):  # last one is today
        write_day(store, day=d, prefix=f"d{d:%d}")
    llm = FakeLLM(facts_reply)
    run = refresh_digests(store, llm, NOW, max_calls=2)
    assert run.created == ["dgd_20261114", "dgd_20261115"] and len(llm.prompts) == 2
    assert not store.has("dgd_20261120")                                              # today is still being written
    assert refresh_digests(store, llm, NOW, max_calls=5).created[0] == "dgd_20261116"


def test_refresh_counts_failures_and_keeps_going(store):
    write_day(store, day=date(2026, 11, 14), prefix="a")
    write_day(store, day=date(2026, 11, 15), prefix="b")
    calls = {"n": 0}

    def flaky(prompt):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("down")
        return facts_reply(prompt)

    run = refresh_digests(store, FakeLLM(flaky), NOW)
    assert run.failed == 1 and run.created == ["dgd_20261115"]


# --- week and month ------------------------------------------------------------------------------------------------

def test_week_digest_needs_two_day_digests_and_month_needs_two_week_digests(store):
    llm = FakeLLM(facts_reply)
    week_start = date(2026, 11, 2)  # a Monday
    write_day(store, day=week_start, prefix="a")
    refresh_digests(store, llm, NOW, max_calls=10)
    assert build_week_digest(store, week_start, llm, NOW) is None                      # only one day digest
    write_day(store, day=week_start + timedelta(days=2), prefix="b")
    refresh_digests(store, llm, NOW, max_calls=10)
    week = build_week_digest(store, week_start, llm, NOW)
    assert week.id == "dgw_20261102" and set(week.derived_from) == {"dgd_20261102", "dgd_20261104"}
    assert build_month_digest(store, (2026, 11), llm, NOW) is None                     # no week digest stored yet


def test_refresh_builds_week_and_month_digests_for_completed_periods(store):
    llm = FakeLLM(facts_reply)
    for d in (date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 13), date(2026, 10, 14)):  # two October weeks
        write_day(store, day=d, prefix=f"x{d:%d}")
    run = refresh_digests(store, llm, NOW, max_calls=20)
    assert {"dgw_20261005", "dgw_20261012", "dgm_202610"} <= set(run.created)
    assert refresh_digests(store, llm, NOW, max_calls=20).created == []                # all up to date


# --- the living profile -----------------------------------------------------------------------------------------------

LONG_PROFILE = ("Goals\nBecome his family's first millionaire through a product and a remote infra job.\n\n"
                "Background and skills\nFinal-year CS student strong in AWS, Kubernetes and Terraform.\n\n"
                "What he avoids\nCold outreach and sending his work to strangers. " * 6)


def living_setup(tmp_path, store):
    profile = tmp_path / "profile" / "profile.md"
    onboarding = tmp_path / "profile" / "onboarding.md"
    living = tmp_path / "profile" / "living.md"
    profile.parent.mkdir(parents=True)
    profile.write_text("Daksh, strong in AWS and Kubernetes.", encoding="utf-8")
    onboarding.write_text("About Daksh: avoids cold outreach.", encoding="utf-8")
    return profile, onboarding, living


def test_living_profile_reads_handwritten_profile_but_never_writes_it(store, tmp_path):
    profile, onboarding, living = living_setup(tmp_path, store)
    llm = FakeLLM(LONG_PROFILE)
    assert update_living_profile(store, "Goal: remote job", llm, NOW, profile, onboarding, living) is True
    assert "strong in AWS and Kubernetes" in llm.prompts[0] and "avoids cold outreach" in llm.prompts[0]
    assert profile.read_text(encoding="utf-8") == "Daksh, strong in AWS and Kubernetes."   # untouched
    assert onboarding.read_text(encoding="utf-8") == "About Daksh: avoids cold outreach."
    assert living.read_text(encoding="utf-8").startswith("# About Daksh")


def test_living_profile_failure_or_junk_leaves_the_previous_file_untouched(store, tmp_path):
    profile, onboarding, living = living_setup(tmp_path, store)
    living.write_text("# About Daksh\nOLD GOOD PROFILE", encoding="utf-8")
    for bad in (RuntimeError("down"), "ok", "x" * 50, json.dumps({"error": "nope"})):
        assert update_living_profile(store, "g", FakeLLM(bad), NOW, profile, onboarding, living) is False
        assert living.read_text(encoding="utf-8") == "# About Daksh\nOLD GOOD PROFILE"
    assert not list(living.parent.glob("*.tmp"))                                        # no temp file left behind


def test_living_profile_includes_recent_week_digests_and_previous_profile_within_a_bound(store, tmp_path):
    profile, onboarding, living = living_setup(tmp_path, store)
    living.write_text("# About Daksh\nPREVIOUS VERSION " + "x" * 12000, encoding="utf-8")
    week = Card(id="dgw_20261109", source="digest", type="thought", title="Week digest", consumed_at=NOW, topic=Topic(primary="uncertain"),
                key_points=[KeyPoint(text="He applied to three jobs this week. (from dgd_1)", topic="uncertain", confidence=1.0)],
                derived_from=["dgd_1", "dgd_2"])
    store.write_card(week)
    llm = FakeLLM(LONG_PROFILE)
    update_living_profile(store, "g" * 5000, llm, NOW, profile, onboarding, living)
    assert "applied to three jobs" in llm.prompts[0] and "PREVIOUS VERSION" in llm.prompts[0]
    assert len(llm.prompts[0]) < 12000


# --- schema / pack integration -----------------------------------------------------------------------------------------

def test_new_card_field_is_optional_so_old_cards_still_load(store):
    old = {"id": "tg_1", "source": "telegram", "type": "thought", "title": "t", "consumed_at": "2026-11-18T10:00:00+05:30",
           "topic": {"primary": "uncertain", "secondary": []}}
    assert Card.model_validate(old).derived_from == []
    assert Card.model_validate({**old, "derived_from": ["a", "b"]}).derived_from == ["a", "b"]


def test_digest_cards_are_searchable_and_enter_the_ask_pack_but_not_recent_entries(store, tmp_path):
    from secondbrain.advisor import build_context
    from secondbrain.embed import HashEmbedder
    from secondbrain.index import Index

    write_day(store, day=date(2026, 11, 14), prefix="p")
    refresh_digests(store, FakeLLM(lambda p: json.dumps({"facts": [{"text": "He worried about rent and applying to recruiters.", "from": ["p_14_0"]}]})), NOW)
    index = Index(tmp_path / "i.db", HashEmbedder())
    index.rebuild(store)
    pack = build_context(store, "worried about rent recruiters", "goals", NOW, index=index)
    assert "worried about rent and applying to recruiters" in pack and "summary dgd_20261114" in pack
    recent = pack.split("RECENT ENTRIES")[1].split("EVIDENCE")[0]
    assert "worried about rent and applying" not in recent                                # digests are not "recent entries"


def test_mentor_profile_text_prefers_the_living_profile(tmp_path):
    from secondbrain.mentor.flow import Mentor
    from test_mentor import FakeClaude, make_mentor

    store = Store(tmp_path / "b")
    m = make_mentor(store, tmp_path, FakeClaude())
    (tmp_path / "profile").mkdir(exist_ok=True)
    (tmp_path / "profile" / "profile.md").write_text("HANDWRITTEN", encoding="utf-8")
    (tmp_path / "profile" / "onboarding.md").write_text("ONBOARDING", encoding="utf-8")
    assert "HANDWRITTEN" in m._profile_text() and "ONBOARDING" in m._profile_text()
    (tmp_path / "profile" / "living.md").write_text("LIVING", encoding="utf-8")
    assert m._profile_text() == "LIVING"
