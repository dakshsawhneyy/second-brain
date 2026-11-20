import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from secondbrain.llm import LLMOutputError
from secondbrain.sessions import (
    chunk_text,
    import_sessions,
    read_session,
    redact_secrets,
)
from secondbrain.store import Store

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)
FAKE_TG = "123456789:" + "A" * 35  # shaped like a bot token, not a real one


# ---------- redaction ----------

@pytest.mark.parametrize("secret", [
    FAKE_TG,
    "sk-abcdefghijklmnopqrstuvwxyz123456",
    "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
    "AKIAABCDEFGHIJKLMNOP",
    "AIza" + "b" * 35,
    "xoxb-1234567890-abcdefghij",
    "gsk_" + "c" * 30,
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcDEF123_-xyz",
])
def test_redacts_known_secret_shapes(secret):
    out = redact_secrets(f"here it is {secret} thanks")
    assert secret not in out and "[REDACTED]" in out and out.startswith("here it is")


def test_redacts_assignments_and_private_keys_and_bearer():
    text = "SB_TELEGRAM_TOKEN=abc123\npassword: hunter2\nAuthorization: Bearer abcdef.ghi\n" \
           "-----BEGIN PRIVATE KEY-----\nMIIE\n-----END PRIVATE KEY-----"
    out = redact_secrets(text)
    for leaked in ("abc123", "hunter2", "abcdef.ghi", "MIIE"):
        assert leaked not in out


def test_plain_text_is_untouched():
    text = "We decided to build the importer with a local model. Time 12:30, ratio 3:4."
    assert redact_secrets(text) == text


# ---------- chunking ----------

def test_chunk_text_splits_on_line_boundaries_and_keeps_everything():
    lines = [f"line {i} " + "x" * 50 for i in range(100)]
    chunks = chunk_text("\n".join(lines), max_chars=500)
    assert all(len(c) <= 500 for c in chunks) and len(chunks) > 5
    assert "\n".join(chunks).count("line ") == 100


def test_chunk_text_hard_splits_a_giant_line():
    chunks = chunk_text("y" * 1200, max_chars=500)
    assert [len(c) for c in chunks] == [500, 500, 200]


# ---------- reading a transcript ----------

def _line(**kw):
    return json.dumps(kw)


def _write_session(path, sid="abc12345-0000", user_text="Please build the session importer for the second brain",
                   extra=()):
    rows = [
        _line(type="ai-title", aiTitle="Build session importer", sessionId=sid),
        _line(type="user", sessionId=sid, timestamp="2026-11-19T10:00:00Z", message={"role": "user", "content": user_text}),
        _line(type="assistant", sessionId=sid, timestamp="2026-11-19T10:01:00Z",
              message={"role": "assistant", "content": [
                  {"type": "thinking", "thinking": "secret thoughts"},
                  {"type": "text", "text": "I will write tests first, then the importer."},
                  {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}]}),
        _line(type="user", sessionId=sid, timestamp="2026-11-19T10:02:00Z",
              message={"role": "user", "content": [{"type": "tool_result", "content": "HUGE TOOL OUTPUT"}]}),
        _line(type="user", sessionId=sid, timestamp="2026-11-19T10:03:00Z", isMeta=True,
              message={"role": "user", "content": "meta noise"}),
        _line(type="assistant", sessionId=sid, isSidechain=True, timestamp="2026-11-19T10:04:00Z",
              message={"role": "assistant", "content": [{"type": "text", "text": "subagent chatter"}]}),
        _line(type="user", sessionId=sid, timestamp="2026-11-19T10:05:00Z",
              message={"role": "user", "content": f"token is {FAKE_TG} <system-reminder>hidden</system-reminder> ok"}),
        "this line is not json",
        *extra,
    ]
    path.write_text("\n".join(rows), encoding="utf-8")


def test_read_session_keeps_only_dialogue_and_redacts(tmp_path):
    f = tmp_path / "abc12345-0000.jsonl"
    _write_session(f)
    s = read_session(f)
    assert s.session_id == "abc12345-0000" and s.title == "Build session importer"
    assert s.started_at == datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc)
    assert s.ended_at == datetime(2026, 11, 19, 10, 5, tzinfo=timezone.utc)
    for banned in ("secret thoughts", "HUGE TOOL OUTPUT", "meta noise", "subagent chatter", "hidden", FAKE_TG):
        assert banned not in s.text
    assert "USER: Please build the session importer" in s.text
    assert "ASSISTANT: I will write tests first" in s.text
    assert "[REDACTED]" in s.text


# ---------- import ----------

class FakeLLM:
    is_local = True
    name = "fake-local"

    def __init__(self, replies=None, fail=False):
        self.calls = 0
        self.fail = fail
        self.replies = replies

    def complete(self, prompt, *, system=None):
        self.calls += 1
        if self.fail:
            return "not json at all"
        if "CHUNK_NOTES" in prompt:
            return json.dumps({"title": "Built the session importer", "topic": "ai/tools",
                               "did": ["wrote tests", "wrote importer"], "decided": ["use local model"],
                               "open": ["schedule it"]})
        return json.dumps({"notes": ["worked on importer"]})


def _old(path):
    past = (NOW - timedelta(hours=2)).timestamp()
    os.utime(path, (past, past))


def _setup(tmp_path):
    projects = tmp_path / "projects"
    (projects / "proj-a").mkdir(parents=True)
    f = projects / "proj-a" / "abc12345-0000.jsonl"
    _write_session(f)
    _old(f)
    return projects, f, Store(tmp_path / "root"), tmp_path / "state.json"


def test_import_writes_private_card_with_summary(tmp_path):
    projects, f, store, state = _setup(tmp_path)
    llm = FakeLLM()
    res = import_sessions(projects, store, state, llm, now=NOW)
    assert res.imported == 1 and res.failed == 0
    cards = list(store.iter_cards())
    assert len(cards) == 1
    c = cards[0]
    assert c.source == "claude-code" and c.visibility == "private" and c.type == "acted"
    assert c.title == "Built the session importer" and c.topic.primary == "ai/tools"
    texts = [k.text for k in c.key_points]
    assert "wrote tests" in texts and any("use local model" in t for t in texts)
    assert c.action is not None and c.action.text == "schedule it"
    assert c.provenance.model == "fake-local"
    assert FAKE_TG not in json.dumps(c.model_dump(mode="json"))


def test_unchanged_session_is_not_resummarised(tmp_path):
    projects, f, store, state = _setup(tmp_path)
    llm = FakeLLM()
    import_sessions(projects, store, state, llm, now=NOW)
    calls = llm.calls
    res = import_sessions(projects, store, state, llm, now=NOW)
    assert res.imported == 0 and res.skipped_unchanged == 1 and llm.calls == calls


def test_changed_session_overwrites_same_card(tmp_path):
    projects, f, store, state = _setup(tmp_path)
    import_sessions(projects, store, state, FakeLLM(), now=NOW)
    _write_session(f, extra=[_line(type="user", timestamp="2026-11-19T11:00:00Z",
                                   message={"role": "user", "content": "one more long request about the importer"})])
    _old(f)
    res = import_sessions(projects, store, state, FakeLLM(), now=NOW)
    assert res.imported == 1 and len(list(store.iter_cards())) == 1


def test_active_session_is_skipped(tmp_path):
    projects, f, store, state = _setup(tmp_path)
    recent = (NOW - timedelta(minutes=2)).timestamp()
    os.utime(f, (recent, recent))
    res = import_sessions(projects, store, state, FakeLLM(), now=NOW)
    assert res.imported == 0 and res.skipped_active == 1 and not list(store.iter_cards())


def test_trivial_session_is_skipped(tmp_path):
    projects, f, store, state = _setup(tmp_path)
    _write_session(f, user_text="hi")
    # only one very short exchange from the user: nothing worth a card
    rows = [r for r in f.read_text(encoding="utf-8").splitlines() if '"assistant"' not in r]
    f.write_text("\n".join(rows[:2]), encoding="utf-8")
    _old(f)
    res = import_sessions(projects, store, state, FakeLLM(), now=NOW)
    assert res.imported == 0 and res.skipped_trivial == 1


def test_excluded_projects_are_ignored(tmp_path):
    projects, f, store, state = _setup(tmp_path)
    tmp_proj = projects / "C--Users-Stormbreaker-AppData-Local-Temp"
    tmp_proj.mkdir()
    g = tmp_proj / "zzz.jsonl"
    _write_session(g, sid="zzz")
    _old(g)
    res = import_sessions(projects, store, state, FakeLLM(), now=NOW)
    assert res.imported == 1
    assert {c.id for c in store.iter_cards()} == {"cc_abc12345-0000"}


def test_limit_caps_work_per_run(tmp_path):
    projects, f, store, state = _setup(tmp_path)
    for i in range(3):
        g = projects / "proj-a" / f"s{i}.jsonl"
        _write_session(g, sid=f"s{i}")
        _old(g)
    res = import_sessions(projects, store, state, FakeLLM(), limit=2, now=NOW)
    assert res.imported == 2


def test_llm_failure_is_counted_and_retried_next_run(tmp_path):
    projects, f, store, state = _setup(tmp_path)
    res = import_sessions(projects, store, state, FakeLLM(fail=True), now=NOW)
    assert res.failed == 1 and res.imported == 0 and not list(store.iter_cards())
    res2 = import_sessions(projects, store, state, FakeLLM(), now=NOW)
    assert res2.imported == 1


def test_non_local_provider_is_refused(tmp_path):
    projects, f, store, state = _setup(tmp_path)

    class Cloud(FakeLLM):
        is_local = False

    with pytest.raises(ValueError, match="local"):
        import_sessions(projects, store, state, Cloud(), now=NOW)


def test_unknown_topic_falls_back_to_uncertain(tmp_path):
    projects, f, store, state = _setup(tmp_path)

    class WeirdTopic(FakeLLM):
        def complete(self, prompt, *, system=None):
            if "CHUNK_NOTES" in prompt:
                return json.dumps({"title": "t", "topic": "made/up", "did": ["x"], "decided": [], "open": []})
            return super().complete(prompt, system=system)

    import_sessions(projects, store, state, WeirdTopic(), now=NOW)
    assert next(store.iter_cards()).topic.primary == "uncertain"


def test_llm_output_error_type_is_exported():
    assert issubclass(LLMOutputError, Exception)


def test_cli_sessions_command_refuses_non_local_router(tmp_path, capsys):
    from secondbrain.cli import run_sessions_command
    from secondbrain.config import load_settings
    from secondbrain.llm import Router

    class Cloud(FakeLLM):
        is_local = False

    projects, f, store, state = _setup(tmp_path)
    settings = load_settings(tmp_path / "root", env={})
    code = run_sessions_command(settings, Router({"triage": Cloud()}), projects, None)
    assert code == 2 and "non-local" in capsys.readouterr().err
    assert not list(store.iter_cards())


def test_cli_sessions_command_imports_with_local_router(tmp_path):
    from secondbrain.cli import run_sessions_command
    from secondbrain.config import load_settings
    from secondbrain.llm import Router

    projects, f, store, state = _setup(tmp_path)
    settings = load_settings(tmp_path / "root", env={})
    lines = []
    code = run_sessions_command(settings, Router({"triage": FakeLLM()}), projects, None, out=lines.append)
    assert code == 0 and "imported=1" in lines[0]
    assert len(list(Store(tmp_path / "root").iter_cards())) == 1


def test_session_project_comes_from_cwd_and_lands_in_card_channel(tmp_path):
    projects, f, store, state = _setup(tmp_path)
    rows = f.read_text(encoding="utf-8").splitlines()
    rows.insert(1, _line(type="user", cwd=r"C:\Studies\Claude Code\z second brain", sessionId="abc12345-0000",
                         timestamp="2026-11-19T09:59:00Z", message={"role": "user", "content": "first long request here"}))
    f.write_text("\n".join(rows), encoding="utf-8")
    _old(f)
    assert read_session(f).project == "z second brain"
    import_sessions(projects, store, state, FakeLLM(), now=NOW)
    assert next(store.iter_cards()).channel == "z second brain"
