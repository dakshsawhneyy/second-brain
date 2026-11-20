import json
import zipfile
from datetime import datetime, timezone

import pytest

from secondbrain.claude_chats import import_chats, load_conversations, to_session
from secondbrain.store import Store

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)
FAKE_TG = "123456789:" + "B" * 35


def _conv(uuid="c1", name="Pricing ideas", updated="2026-11-18T10:00:00.000000Z", extra_msgs=()):
    msgs = [
        {"sender": "human", "text": "I want to price my SkipATS-like tool for students, thoughts?", "content": []},
        {"sender": "assistant", "text": "", "content": [{"type": "text", "text": "Start with a free tier and test willingness to pay."}]},
        {"sender": "human", "text": f"my key is {FAKE_TG} and I will try 3 price points", "content": []},
        *extra_msgs,
    ]
    return {"uuid": uuid, "name": name, "created_at": "2026-11-18T09:00:00.000000Z",
            "updated_at": updated, "chat_messages": msgs}


def _drop(tmp_path, convs, as_zip=True):
    d = tmp_path / "chats"
    d.mkdir()
    payload = json.dumps(convs)
    if as_zip:
        with zipfile.ZipFile(d / "data-2026-11-19.zip", "w") as z:
            z.writestr("conversations.json", payload)
            z.writestr("users.json", "[]")
    else:
        (d / "conversations.json").write_text(payload, encoding="utf-8")
    return d


class FakeLLM:
    is_local = True
    name = "fake-local"

    def complete(self, prompt, *, system=None):
        if "CHUNK_NOTES" in prompt:
            return json.dumps({"title": "Pricing for a student tool", "topic": "business/saas-pricing",
                               "did": ["compared price points"], "decided": ["start free"], "open": ["test 3 prices"]})
        return json.dumps({"notes": ["pricing"]})


def test_loads_conversations_from_zip_and_plain_json(tmp_path):
    assert load_conversations(_drop(tmp_path, [_conv()]) / "data-2026-11-19.zip")[0]["uuid"] == "c1"
    d2 = tmp_path / "other"
    d2.mkdir()
    (d2 / "conversations.json").write_text(json.dumps([_conv("c2")]), encoding="utf-8")
    assert load_conversations(d2 / "conversations.json")[0]["uuid"] == "c2"


def test_to_session_reads_text_or_content_blocks_and_redacts():
    s = to_session(_conv())
    assert s.session_id == "c1" and s.title == "Pricing ideas" and s.turns == 3
    assert "ASSISTANT: Start with a free tier" in s.text and "USER: I want to price" in s.text
    assert FAKE_TG not in s.text and "[REDACTED]" in s.text


def test_import_chats_writes_private_cards_and_skips_unchanged(tmp_path):
    d = _drop(tmp_path, [_conv()])
    store, state = Store(tmp_path / "root"), tmp_path / "state.json"
    res = import_chats(d, store, state, FakeLLM(), now=NOW)
    assert res.imported == 1
    c = next(store.iter_cards())
    assert c.id == "ch_c1" and c.source == "claude-chat" and c.visibility == "private"
    assert c.topic.primary == "business/saas-pricing" and c.type == "thought"
    again = import_chats(d, store, state, FakeLLM(), now=NOW)
    assert again.imported == 0 and again.skipped_unchanged == 1


def test_updated_conversation_overwrites_same_card(tmp_path):
    d = _drop(tmp_path, [_conv()])
    store, state = Store(tmp_path / "root"), tmp_path / "state.json"
    import_chats(d, store, state, FakeLLM(), now=NOW)
    (d / "data-2026-11-19.zip").unlink()
    with zipfile.ZipFile(d / "data-2026-12-01.zip", "w") as z:
        z.writestr("conversations.json", json.dumps([_conv(updated="2026-11-25T10:00:00.000000Z")]))
    res = import_chats(d, store, state, FakeLLM(), now=NOW)
    assert res.imported == 1 and len(list(store.iter_cards())) == 1


def test_empty_or_trivial_conversation_is_skipped(tmp_path):
    d = _drop(tmp_path, [{"uuid": "t", "name": "x", "created_at": "2026-11-18T09:00:00Z",
                          "updated_at": "2026-11-18T09:01:00Z",
                          "chat_messages": [{"sender": "human", "text": "hi", "content": []}]}])
    res = import_chats(d, Store(tmp_path / "root"), tmp_path / "state.json", FakeLLM(), now=NOW)
    assert res.imported == 0 and res.skipped_trivial == 1


def test_non_local_provider_refused(tmp_path):
    class Cloud(FakeLLM):
        is_local = False

    with pytest.raises(ValueError, match="local"):
        import_chats(_drop(tmp_path, [_conv()]), Store(tmp_path / "root"), tmp_path / "s.json", Cloud(), now=NOW)


def test_missing_drop_folder_is_an_empty_result(tmp_path):
    res = import_chats(tmp_path / "nope", Store(tmp_path / "root"), tmp_path / "s.json", FakeLLM(), now=NOW)
    assert res.imported == 0


def test_sync_command_logs_one_line_and_runs_both_sources(tmp_path):
    from secondbrain.cli import run_sync_command
    from secondbrain.config import load_settings
    from secondbrain.llm import Router
    from test_sessions import _setup

    projects, f, store, state = _setup(tmp_path)
    settings = load_settings(tmp_path / "root", env={})
    drop = settings.raw_dir / "claude-chats"
    drop.mkdir(parents=True)
    with zipfile.ZipFile(drop / "export.zip", "w") as z:
        z.writestr("conversations.json", json.dumps([_conv()]))
    code = run_sync_command(settings, Router({"triage": FakeLLM()}), projects, 3,
                            now=lambda: datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc))
    assert code == 0
    log = (settings.raw_dir / "sync.log").read_text(encoding="utf-8").strip().splitlines()
    assert len(log) == 1 and "sessions: imported=1" in log[0] and "chats: imported=1" in log[0] and "exit=0" in log[0]
