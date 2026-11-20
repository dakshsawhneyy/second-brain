import asyncio
import itertools
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from secondbrain import usage
from secondbrain.advisor import AdviceError
from secondbrain.mentor import ledger, onboarding
from secondbrain.mentor.flow import Mentor
from secondbrain.mentor.guards import check
from secondbrain.mentor.persona import PERSONA
from secondbrain.store import Store

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 11, 20, 9, 0, tzinfo=IST)
OWNER = 1434918489

_VOCAB = ("river stone window candle harbor engine copper meadow lantern orbit saddle pepper anchor velvet ladder "
          "marble thunder pocket garden mirror bridge falcon ribbon summit cellar plume anvil harvest tunnel glacier "
          "compass willow quartz blanket forest desert signal paddle cobalt lagoon timber rocket spruce amber tablet "
          "ferry canyon mortar valley sketch beacon trowel meteor juniper walnut cradle radish hammock zephyr "
          "bobbin cinder thicket quiver loom parsley fjord nickel gable ember kettle quarry sparrow trellis").split()
# 150 distinct, rule-abiding sentences: no digits, no banned phrases, trigrams almost never shared
SENTENCES = [" ".join(_VOCAB[(i * 5 + j) % len(_VOCAB)] for j in range(8)) + " noted." for i in range(150)]


class FakeClaude:
    """Returns distinct, rule-abiding sentences; remembers every system prompt and prompt it was given."""

    def __init__(self, replies=None):
        self.calls: list[tuple[str, str]] = []
        self._it = itertools.cycle(replies or SENTENCES)

    def __call__(self, system: str, prompt: str) -> str:
        self.calls.append((system, prompt))
        return next(self._it)


class FakeLocal:
    name, is_local = "fake", True

    def complete(self, prompt, *, system=None):
        return '{"category": "distraction"}'


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "brain")


def make_mentor(store, tmp_path, runner=None, local=None):
    return Mentor(store, tmp_path / "raw" / "mentor_state.json", runner or FakeClaude(), local_llm=local,
                  goals_text="Focus: land a remote infra job", profile_path=tmp_path / "profile" / "profile.md")


def finish_onboarding(m, start=NOW):
    m.start_onboarding(start)
    for i in range(onboarding.TOTAL):
        m.handle_onboarding_answer(f"my honest answer number {i}", start + timedelta(minutes=i + 1), 100 + i)


# --- telemetry -----------------------------------------------------------------------------------------

def test_usage_log_attributes_sections_and_builds_a_report(tmp_path):
    log = tmp_path / "usage.jsonl"
    usage.configure(log)
    try:
        import time
        t0 = time.monotonic()
        with usage.section("mentor.morning"):
            usage.log_call(provider="claude", model="m", ok=True, started=t0, input_tokens=10, output_tokens=5,
                           cache_write_tokens=1000, cost_usd=0.01, now=NOW)
        with usage.section("sync.sessions"):
            usage.log_call(provider="ollama", model="q", ok=True, started=t0, input_tokens=100, output_tokens=50, now=NOW)
        usage.log_call(provider="claude", model="m", ok=False, started=t0, error="timeout", now=NOW + timedelta(hours=7))
    finally:
        usage.configure(None)
    rows = usage.read_rows(log)
    assert [r["section"] for r in rows] == ["mentor.morning", "sync.sessions", "unlabeled"]
    assert not any(k in ("prompt", "text", "answer") for r in rows for k in r)  # sizes only, never text
    rep = usage.build_report(rows, NOW - timedelta(days=1))
    assert rep.claude_by_section["mentor.morning"].all_in == 1010 and rep.claude_total.calls == 2
    assert rep.local_by_section["sync.sessions"].calls == 1 and rep.peak_window_calls == 1
    text = usage.format_report(rep, 1)
    assert "mentor.morning" in text and "LOCAL" in text and "Busiest 5-hour window" in text


def test_claude_runner_logs_real_tokens_from_json_output(tmp_path, monkeypatch):
    from secondbrain import advisor

    payload = {"result": "Do the hard one first.", "total_cost_usd": 0.0044, "is_error": False,
               "usage": {"input_tokens": 2, "cache_creation_input_tokens": 1099, "cache_read_input_tokens": 5,
                         "output_tokens": 9}}
    monkeypatch.setattr(advisor.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr=""))
    usage.configure(tmp_path / "u.jsonl")
    try:
        with usage.section("ask"):
            assert advisor.claude_cli_runner("sys", "prompt") == "Do the hard one first."
    finally:
        usage.configure(None)
    row = usage.read_rows(tmp_path / "u.jsonl")[0]
    assert row["section"] == "ask" and row["in_tokens"] == 2 and row["cache_write"] == 1099 and row["out_tokens"] == 9
    assert row["cost_usd"] == 0.0044 and row["ok"] is True


def test_claude_runner_reports_failures(tmp_path, monkeypatch):
    from secondbrain import advisor

    monkeypatch.setattr(advisor.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="rate limited"))
    usage.configure(tmp_path / "u.jsonl")
    try:
        with pytest.raises(AdviceError):
            advisor.claude_cli_runner("s", "p")
    finally:
        usage.configure(None)
    assert usage.read_rows(tmp_path / "u.jsonl")[0]["ok"] is False


# --- ledger ---------------------------------------------------------------------------------------------

def test_parse_commitments_detects_vague_when_bet_and_limits_to_three():
    items, dropped = ledger.parse_commitments(
        "1. send 2 applications to Acme at 10:00\n2) learn terraform\n- write the landing page copy by noon\n"
        "- call mom #other\nsomething else")
    assert dropped == 2 and len(items) == 3
    assert items[0].bet == "job" and items[0].when == "10:00" and not items[0].vague
    assert items[1].vague
    assert items[2].when == "by noon"


def test_looks_like_commitments_ignores_journal_text():
    assert ledger.looks_like_commitments("send two applications by noon")
    assert not ledger.looks_like_commitments("I feel stuck today and I am not sure why " * 8)
    assert not ledger.looks_like_commitments("just thinking out loud")


def test_mentor_day_has_a_4am_cutoff_and_ids_continue(store):
    assert ledger.mentor_day(NOW.replace(hour=2)) == NOW.date() - timedelta(days=1)
    items, _ = ledger.parse_commitments("send one email at 10:00")
    a = ledger.create_commitments(store, items, NOW)
    b = ledger.create_commitments(store, items, NOW + timedelta(hours=1))
    assert [c.id for c in a + b] == ["mc_20261120_1", "mc_20261120_2"]
    assert store.read_card("mc_20261120_1").mentor.status == "open"


def test_close_item_stats_and_tone(store):
    items, _ = ledger.parse_commitments("send one email at 10:00\npublish the post by noon")
    c1, c2 = ledger.create_commitments(store, items, NOW)
    ledger.close_item(store, c1.id, "kept", proof="https://x.y")
    ledger.close_item(store, c2.id, "missed", reason="got distracted")
    later = NOW + timedelta(days=1)
    assert ledger.keep_stats(store, later) == (1, 1)
    assert ledger.tone_for(store, later, 1) == "disappointed"       # first miss, reason given
    facts = ledger.build_facts(store, later)
    assert any(f.startswith("[mc_20261120_2]") and "status=missed" in f for f in facts)
    assert any(f.startswith("[pattern_job]") for f in facts)


# --- guards ----------------------------------------------------------------------------------------------

def _check(text, **kw):
    base = dict(kind="daily", tone="warm", allowed_ids=set(), allowed_text="", recent=[])
    base.update(kw)
    return check(text, **base)


def test_guards_catch_each_rule():
    assert _check("Fine. Do the hard one first.") == []
    assert "too_long" in _check("word " * 200)
    assert "format" in _check("Do it now!") and "format" in _check("- bullet one\n- bullet two")
    assert "banned_phrase" in _check("Great job today.") and "banned_phrase" in _check("You're right, take a rest.")
    assert "banned_phrase" in _check("When I was your age I built a company.")
    assert "unsafe_advice" in _check("Just skip dinner and sleep less.")
    assert "person_attack" in _check("You're lazy, that's the problem.")
    assert "raises_target" in _check("Tomorrow double your applications to make up for it.")
    assert "unknown_id" in _check("See [mc_1].") and _check("See [mc_1].", allowed_ids={"mc_1"}) == []
    assert "invented_number" in _check("You sent 47 applications.") and _check("You sent 47.", allowed_text="47 apps") == []
    assert "goals_while_concerned" in _check("Fix the application first.", tone="concerned")
    assert "repetition" in _check("Okay. Let's look at what happened today.", recent=["Okay. Let's look at what happened today."])


def test_truth_over_comfort_is_in_the_persona_and_flattery_is_blocked():
    flat = " ".join(PERSONA.split())
    assert "TRUTH OVER COMFORT" in flat and "what he needs to hear, not what he wants to hear" in flat
    assert "What are you doing, Daksh?" in flat
    assert "banned_phrase" in _check("You're right to feel that way, absolutely.")


# --- onboarding (M0) --------------------------------------------------------------------------------------

def test_onboarding_runs_end_to_end_and_writes_the_profile(store, tmp_path):
    claude = FakeClaude()
    m = make_mentor(store, tmp_path, claude)
    assert m.onboarding_due(NOW) and not m.onboarding_due(NOW.replace(hour=3))
    first = m.start_onboarding(NOW)
    assert first and m.awaiting() == "onboarding" and not m.onboarding_due(NOW)
    assert "coachable" in claude.calls[0][1]
    for i in range(onboarding.TOTAL):
        reply = m.handle_onboarding_answer(f"answer {i}", NOW + timedelta(minutes=i + 1), 100 + i)
        assert reply
    assert m.awaiting() is None and m.state.load()["done"] is True
    assert (tmp_path / "profile" / "profile.md").read_text(encoding="utf-8").startswith("# About Daksh")
    assert store.read_card("mo_100").key_points[1].text == "A: answer 0"
    assert m.phase(NOW + timedelta(days=1)) == 1 and m.phase(NOW + timedelta(days=12)) == 2


def test_onboarding_survives_claude_errors_with_plain_questions(store, tmp_path):
    def broken(system, prompt):
        raise AdviceError("offline")

    m = make_mentor(store, tmp_path, broken)
    assert "coachable" in m.start_onboarding(NOW)
    nxt = m.handle_onboarding_answer("yes", NOW + timedelta(minutes=1), 1)
    assert nxt == onboarding.group_text(1)


# --- commitments and close-out (M1, M3) ---------------------------------------------------------------------

def test_full_day_morning_commit_sharpen_evening_closeout(store, tmp_path):
    claude = FakeClaude()
    m = make_mentor(store, tmp_path, claude, FakeLocal())
    finish_onboarding(m)
    day2 = NOW + timedelta(days=1)
    assert m.morning_text(day2) and m.awaiting() == "commitments"
    assert "frightening" in claude.calls[-1][1]
    assert m.handle_commitments("just thinking aloud " * 20, day2, 5) is None      # a journal, not a plan
    reply = m.handle_commitments("send 2 applications to Acme at 10:00\nlearn terraform", day2, 6)
    assert "[mc_20261121_1]" in reply and "[mc_20261121_2] is vague" in reply
    reply = m.handle_commitments("write the terraform module README by 5pm", day2, 7)
    assert reply.startswith("Locked: [mc_20261121_2]") and not store.read_card("mc_20261121_2").mentor.vague
    assert m.awaiting() is None

    evening = day2.replace(hour=22)
    assert m.evening_text(evening) and m.awaiting() == "closeout"
    assert "Go through today's open commitments" in claude.calls[-1][1]
    out = m.handle_closeout("1 done https://example.com/apps\n2 missed got distracted by YouTube", evening, 8)
    assert out and m.awaiting() is None
    c1, c2 = store.read_card("mc_20261121_1"), store.read_card("mc_20261121_2")
    assert c1.mentor.status == "kept" and c1.mentor.evidence == "claimed" and c1.mentor.evidence_refs == ["https://example.com/apps"]
    assert c2.mentor.status == "missed" and c2.mentor.miss_category == "distraction"
    assert store.read_card("mk_20261121").type == "checkin"
    assert any("never raise or double" in c[1].lower() for c in claude.calls)


def test_closeout_free_text_goes_through_the_local_model_and_junk_is_not_swallowed(store, tmp_path):
    class Parser:
        name, is_local = "fake", True
        def complete(self, prompt, *, system=None):
            if "category" in prompt:
                return '{"category": "other"}'
            return '{"items": [{"index": 1, "status": "done", "proof": "sent", "reason": null}]}'

    m = make_mentor(store, tmp_path, FakeClaude(), Parser())
    finish_onboarding(m)
    day2 = NOW + timedelta(days=1)
    ledger.create_commitments(store, ledger.parse_commitments("send one email at 10:00")[0], day2)
    m.state.update(awaiting="closeout")
    assert m.handle_closeout("I sent that email in the end", day2.replace(hour=22), 9)
    assert store.read_card("mc_20261121_1").mentor.status == "kept"
    ledger.create_commitments(store, ledger.parse_commitments("call the recruiter at noon")[0], day2)
    m.state.update(awaiting="closeout")
    assert m.handle_closeout("ok", day2.replace(hour=22), 10).startswith("Use the short form")
    assert m.handle_closeout("long journal " * 20, day2.replace(hour=22), 11) is None  # falls through to normal capture


def test_guard_failures_fall_back_to_plain_templates(store, tmp_path):
    bad = FakeClaude(["Great job, amazing work!"] * 10)
    m = make_mentor(store, tmp_path, bad)
    finish_onboarding(m)
    text = m.morning_text(NOW + timedelta(days=1))
    assert text.startswith("State one to three outputs")           # template, not the flattering draft
    assert len([c for c in bad.calls if "rewrite" in c[1].lower()]) >= 1  # it was given one chance to fix it


# --- free chat (/ask) --------------------------------------------------------------------------------------------

def test_ask_is_vikram_with_facts_and_is_logged(store, tmp_path):
    claude = FakeClaude(["What are you doing, Daksh? She is not on your list for this year."])
    m = make_mentor(store, tmp_path, claude)
    finish_onboarding(m)
    ledger.create_commitments(store, ledger.parse_commitments("send one email at 10:00")[0], NOW)
    answer = m.ask("should I text her tonight instead of working?", NOW, 77)
    assert answer.startswith("What are you doing")
    system, prompt = claude.calls[-1]
    assert "TRUTH OVER COMFORT" in system and "[mc_20261120_1]" in prompt and "ABOUT HIM" in prompt
    assert store.read_card("adv_77").source == "advice"


def test_ask_blocks_unsafe_or_insulting_answers(store, tmp_path):
    m = make_mentor(store, tmp_path, FakeClaude(["You're lazy and worthless, skip dinner."]))
    with pytest.raises(AdviceError):
        m.ask("what should I do?", NOW, 78)
    assert store.has("adq_78")  # his question is kept even though no answer was sent


# --- bot wiring ----------------------------------------------------------------------------------------------------

class _Msg:
    def __init__(self, text, mid, date=None):
        self.text, self.message_id, self.date, self.replies = text, mid, date, []

    async def reply_text(self, text, **kw):
        self.replies.append(text)


def _update(text, mid=1, date=None):
    return SimpleNamespace(effective_user=SimpleNamespace(id=OWNER), effective_chat=SimpleNamespace(id=OWNER, type="private"),
                           message=_Msg(text, mid, date), callback_query=None)


def _ctx(store, mentor, tmp_path):
    return SimpleNamespace(bot_data={"store": store, "goals_text": "", "owner_id": OWNER, "now": lambda: NOW,
                                     "state_path": tmp_path / "raw" / "bot_state.json", "mentor": mentor}, args=[])


def test_plain_text_is_routed_to_the_mentor_only_while_it_is_waiting(store, tmp_path):
    from secondbrain.bot.app import on_text

    m = make_mentor(store, tmp_path)
    finish_onboarding(m)
    ctx = _ctx(store, m, tmp_path)
    u = _update("an ordinary thought about my day, nothing to commit to", 301)
    asyncio.run(on_text(u, ctx))
    assert u.message.replies == ["Saved: thought"]                       # not waiting: normal capture
    m.state.update(awaiting="commitments")
    u = _update("send 2 applications to Acme at 10:00", 302, NOW.astimezone(timezone.utc) + timedelta(days=1))
    asyncio.run(on_text(u, ctx))
    assert u.message.replies[0].startswith("Locked in") and store.has("mc_20261121_1")


def test_usage_command_reports_by_section(store, tmp_path):
    from secondbrain.bot.app import cmd_usage

    log = tmp_path / "raw" / "usage.jsonl"
    log.parent.mkdir(parents=True)
    row = {"ts": NOW.isoformat(), "section": "mentor.morning", "provider": "claude", "model": "m", "kind": "llm", "ok": True,
           "secs": 4.2, "in_tokens": 3, "out_tokens": 60, "cache_read": 0, "cache_write": 1100, "cost_usd": 0.01}
    log.write_text(json.dumps(row) + "\n", encoding="utf-8")
    u = _update("/usage")
    asyncio.run(cmd_usage(u, _ctx(store, None, tmp_path)))
    text = "\n".join(u.message.replies)
    assert "mentor.morning" in text and "1,163 tok" in text


def test_facts_do_not_claim_a_history_that_does_not_exist(store):
    facts = ledger.build_facts(store, NOW)
    assert len(facts) == 1 and facts[0].startswith("[pattern_start]") and "no commitments are on record" in facts[0]
    ledger.create_commitments(store, ledger.parse_commitments("send one email at 10:00")[0], NOW)
    later = ledger.build_facts(store, NOW + timedelta(days=1))
    assert any(f.startswith("[pattern_total]") and "1" in f for f in later)
    assert any(f.startswith("[pattern_job]") and "none kept yet among the 1" in f for f in later)
