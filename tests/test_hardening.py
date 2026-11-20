import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from secondbrain.advisor import LOCAL_ONLY, build_context
from secondbrain.backup import BackupError, backup_name, make_backup, restore_backup
from secondbrain.bot.app import due_alerts
from secondbrain.bot.brief import build_morning_brief
from secondbrain.embed import HashEmbedder
from secondbrain.index import Index
from secondbrain.schema import Action, Card, KeyPoint, Topic
from secondbrain.store import Store

NOW = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)


def _card(cid, source="telegram", type_="thought", text="x", hours_ago=2, channel=None, action=None, points=None):
    return Card(id=cid, source=source, type=type_, title=text[:80], consumed_at=NOW - timedelta(hours=hours_ago),
                topic=Topic(primary="uncertain"), channel=channel,
                key_points=[KeyPoint(text=p, topic="uncertain", confidence=1.0) for p in (points if points is not None else [text])],
                action=Action(text=action) if action else None)


# --- 6: incremental index + /ask uses it ------------------------------------------------------------

def test_index_update_adds_changes_and_removes_without_a_full_rebuild(tmp_path):
    store = Store(tmp_path / "b")
    idx = Index(tmp_path / "i.db", HashEmbedder())
    store.write_card(_card("tg_1", text="negotiating the salary for the offer"))
    assert idx.update(store) == (1, 0, 1)                      # first run builds
    store.write_card(_card("tg_2", text="kubernetes ingress is confusing"))
    assert idx.update(store) == (1, 0, 2)                      # only the new card is embedded
    assert idx.update(store) == (0, 0, 2)                      # nothing changed: nothing embedded
    store.write_card(_card("tg_2", text="kubernetes ingress finally makes sense"))
    assert idx.update(store) == (1, 0, 2)                      # edited card re-embedded
    assert [h.card_id for h in idx.search("kubernetes ingress", k=1)] == ["tg_2"]
    store.write_card(_card("tg_2", text="gone").model_copy(update={"tier": "cold"}))
    assert idx.update(store) == (0, 1, 1)                      # cold card leaves the index


def test_ask_pack_uses_the_index_but_never_local_only_or_session_cards(tmp_path):
    store = Store(tmp_path / "b")
    store.write_card(_card("tg_1", text="my brother and I argue about money", hours_ago=24 * 60))
    store.write_card(_card("tg_2", text="private money fear", hours_ago=24 * 60, channel=LOCAL_ONLY))
    store.write_card(_card("cc_1", source="claude-code", text="money module refactor", hours_ago=24 * 60))
    idx = Index(tmp_path / "i.db", HashEmbedder())
    idx.update(store)
    pack = build_context(store, "money", "", NOW, index=idx)
    assert "brother" in pack and "private money fear" not in pack and "refactor" not in pack


def test_ask_pack_survives_a_broken_index(tmp_path):
    class Broken:
        def search(self, *a, **k):
            raise RuntimeError("no model")

    store = Store(tmp_path / "b")
    store.write_card(_card("tg_1", text="salary question about the offer", hours_ago=24 * 60))
    assert "salary" in build_context(store, "salary offer", "", NOW, index=Broken())


# --- 5: encrypted backup ----------------------------------------------------------------------------

def test_backup_round_trip_and_wrong_passphrase(tmp_path):
    root = tmp_path / "brain"
    store = Store(root)
    store.write_card(_card("tg_1", text="my secret journal line"))
    dest = tmp_path / "cloud"
    path = make_backup(root, dest, "correct horse", NOW)
    assert path.name == backup_name(NOW)
    assert b"secret journal" not in path.read_bytes()          # encrypted at rest
    with pytest.raises(BackupError):
        restore_backup(path, "wrong", tmp_path / "r1")
    n = restore_backup(path, "correct horse", tmp_path / "r2")
    assert n >= 1
    assert Store(tmp_path / "r2").read_card("tg_1").title.startswith("my secret")
    with pytest.raises(BackupError):                            # never merges into an existing memory
        restore_backup(path, "correct horse", tmp_path / "r2")


def test_backup_refuses_without_passphrase_and_prunes(tmp_path):
    root = tmp_path / "brain"
    Store(root).write_card(_card("tg_1"))
    with pytest.raises(BackupError):
        make_backup(root, tmp_path / "d", None, NOW)
    for i in range(5):
        make_backup(root, tmp_path / "d", "pw", NOW + timedelta(days=i), keep=3)
    assert len(list((tmp_path / "d").glob("*.sbk"))) == 3


# --- 8: failures must reach him ---------------------------------------------------------------------

def _log(tmp_path, line):
    p = tmp_path / "sync.log"
    p.write_text(line + "\n", encoding="utf-8")
    return p


def test_alerts_for_failed_stale_and_unconfigured_backup(tmp_path):
    ok = f"{(NOW - timedelta(hours=1)).isoformat(timespec='seconds')} | sessions: x | backup: ok | exit=0"
    assert due_alerts(NOW, {}, _log(tmp_path, ok)) == []
    failed = ok.replace("exit=0", "exit=1")
    assert [k for k, _ in due_alerts(NOW, {}, _log(tmp_path, failed))] == ["sync_failed"]
    stale = f"{(NOW - timedelta(hours=30)).isoformat(timespec='seconds')} | sessions: x | backup: ok | exit=0"
    assert [k for k, _ in due_alerts(NOW, {}, _log(tmp_path, stale))] == ["sync_stale"]
    nobackup = ok.replace("backup: ok", "backup: not set up")
    assert [k for k, _ in due_alerts(NOW, {}, _log(tmp_path, nobackup))] == ["backup"]
    # once sent, not repeated the same day (sync) or for a week (backup)
    state = {"alert_backup": NOW.date().isoformat()}
    assert due_alerts(NOW, state, _log(tmp_path, nobackup)) == []
    assert due_alerts(NOW + timedelta(days=8), state, _log(tmp_path, nobackup.replace(ok.split(" | ")[0], (NOW + timedelta(days=8)).isoformat(timespec="seconds")))) != []
    assert due_alerts(NOW, {}, tmp_path / "missing.log") == []


# --- 9: duplicates and finished leftovers ------------------------------------------------------------

def test_same_leftover_from_two_sessions_is_listed_once(tmp_path):
    store = Store(tmp_path)
    for i in (1, 2):
        store.write_card(_card(f"cc_{i}", source="claude-code", channel="z second brain", hours_ago=30 + i,
                               text="session", action="Add retry limit to the follow-up prompt"))
    text = build_morning_brief(store, "", NOW).text
    assert text.count("retry limit") == 1


def test_leftover_a_later_session_completed_disappears(tmp_path):
    store = Store(tmp_path)
    store.write_card(_card("cc_1", source="claude-code", channel="z second brain", hours_ago=50, text="old",
                           action="Regenerate the bot token"))
    store.write_card(_card("cc_2", source="claude-code", channel="z second brain", hours_ago=10, text="later",
                           points=["Regenerated the bot token and updated the env file"]))
    assert "bot token" not in build_morning_brief(store, "", NOW).text


def test_his_own_done_resolves_his_todo(tmp_path):
    store = Store(tmp_path)
    store.write_card(_card("tg_1", text="todo", hours_ago=30, action="Send five job applications"))
    store.write_card(_card("tg_2", type_="acted", text="Sent five job applications", hours_ago=3))
    assert "Send five" not in build_morning_brief(store, "", NOW).text.split("Today's one action:")[1]


def test_unrelated_later_card_does_not_hide_an_open_item(tmp_path):
    store = Store(tmp_path)
    store.write_card(_card("tg_1", text="todo", hours_ago=30, action="Send five job applications"))
    store.write_card(_card("tg_2", type_="acted", text="Fixed the login bug", hours_ago=3))
    assert "Send five job applications" in build_morning_brief(store, "", NOW).text


# --- sync line ---------------------------------------------------------------------------------------

def test_sync_logs_index_and_backup_status(tmp_path):
    from secondbrain.cli import run_sync_command
    from secondbrain.config import load_settings
    from secondbrain.llm import Router

    class LLM:
        name, is_local = "fake", True
        def complete(self, prompt, *, system=None): return "{}"

    root = tmp_path / "brain"
    Store(root).write_card(_card("tg_1", text="hello world note"))
    projects = tmp_path / "projects"
    projects.mkdir()
    settings = load_settings(root=root, env={"SB_BACKUP_DIR": str(tmp_path / "cloud"), "SB_BACKUP_PASSPHRASE": "pw"})
    code = run_sync_command(settings, Router({"triage": LLM()}), projects, 3, now=lambda: NOW, embedder=HashEmbedder())
    line = (root / "raw" / "sync.log").read_text(encoding="utf-8").strip()
    assert code == 0 and "index: +1 -0 =1" in line and "backup: ok" in line and line.endswith("exit=0")
    run_sync_command(settings, Router({"triage": LLM()}), projects, 3, now=lambda: NOW, embedder=HashEmbedder())
    assert "backup: ok (today)" in (root / "raw" / "sync.log").read_text(encoding="utf-8")
    nopw = load_settings(root=root, env={})
    run_sync_command(nopw, Router({"triage": LLM()}), projects, 3, now=lambda: NOW + timedelta(days=1))
    assert "backup: not set up" in (root / "raw" / "sync.log").read_text(encoding="utf-8").splitlines()[-1]


# --- Ollama embeddings --------------------------------------------------------------------------------

def test_ollama_embedder_posts_to_loopback_and_parses():
    import httpx
    from secondbrain.embed import OllamaEmbedder

    seen = {}

    def handler(request):
        seen["url"], seen["body"] = str(request.url), json.loads(request.content)
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2], [0.3, 0.4]]})

    emb = OllamaEmbedder(client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert emb.embed(["a", "b"]) == [[0.1, 0.2], [0.3, 0.4]]
    assert seen["url"] == "http://localhost:11434/api/embed" and seen["body"]["input"] == ["a", "b"]
    assert emb.embed([]) == []


def test_ollama_embedder_rejects_a_malformed_reply():
    import httpx
    from secondbrain.embed import OllamaEmbedder

    emb = OllamaEmbedder(client=httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"embeddings": [[1.0]]}))))
    with pytest.raises(RuntimeError):
        emb.embed(["a", "b"])


def test_changing_the_embedder_forces_a_rebuild_instead_of_mixing_vectors(tmp_path):
    class Other(HashEmbedder):
        name = "other:model"

    store = Store(tmp_path / "b")
    store.write_card(_card("tg_1", text="hello there friend"))
    Index(tmp_path / "i.db", HashEmbedder()).update(store)
    assert Index(tmp_path / "i.db", Other(dim=32)).update(store) == (1, 0, 1)   # rebuilt, not "0 changed"
    assert Index(tmp_path / "i.db", Other(dim=32)).update(store) == (0, 0, 1)   # now incremental again
