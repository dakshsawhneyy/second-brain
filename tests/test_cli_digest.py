import json
import os
import time as timelib
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from secondbrain.cli import build_parser, run_digest_command, run_sync_command
from secondbrain.config import load_settings
from secondbrain.digest import living_profile_due
from secondbrain.llm import Router
from secondbrain.schema import Card, KeyPoint, Topic
from secondbrain.store import Store

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 11, 20, 12, 0, tzinfo=IST)
DAY = date(2026, 11, 18)

PROFILE_TEXT = "Goals\nRemote infra job and a product.\n\nPressures\nMoney and family. " * 10


class FnProvider:
    is_local, name = True, "fake-local"

    def __init__(self, fn):
        self.fn = fn

    def complete(self, prompt, *, system=None):
        return self.fn(prompt, system)


def model(prompt, system):
    import re
    if system and "profile of a person" in system:
        return PROFILE_TEXT
    ids = re.findall(r"^\[([^\]]+)\]", prompt, flags=re.M)[:2]
    return json.dumps({"facts": [{"text": "He thought about his plan.", "from": ids}]})


def router_with(fn):
    p = FnProvider(fn)
    return Router({"triage": p, "extract": p, "synthesis": p})


def seed(root: Path, n=3):
    store = Store(root)
    for i in range(n):
        store.write_card(Card(id=f"tg_{i}", source="telegram", type="thought", title=f"note {i}",
                              consumed_at=datetime.combine(DAY, time(9 + i), tzinfo=IST), topic=Topic(primary="uncertain"),
                              key_points=[KeyPoint(text=f"note {i} about the plan", topic="uncertain", confidence=1.0)]))
    return store


def test_parser_has_digest_command():
    args = build_parser().parse_args(["digest", "--profile"])
    assert args.command == "digest" and args.profile is True


def test_digest_command_creates_digests_and_reports(tmp_path):
    settings = load_settings(root=tmp_path, env={})
    seed(tmp_path)
    lines: list[str] = []
    assert run_digest_command(settings, FnProvider(model), NOW, out=lines.append) == 0
    assert any("created 1" in l for l in lines) and Store(tmp_path).has("dgd_20261118")


def test_digest_command_profile_flag_writes_living_md_without_touching_profile_md(tmp_path):
    settings = load_settings(root=tmp_path, env={})
    seed(tmp_path)
    settings.profile_path.parent.mkdir(parents=True, exist_ok=True)
    settings.profile_path.write_text("MY OWN PROFILE", encoding="utf-8")
    lines: list[str] = []
    run_digest_command(settings, FnProvider(model), NOW, force_profile=True, out=lines.append)
    assert settings.living_profile_path.read_text(encoding="utf-8").startswith("# About Daksh")
    assert settings.profile_path.read_text(encoding="utf-8") == "MY OWN PROFILE"
    assert any("profile: updated" in l for l in lines)


def test_living_profile_is_due_when_missing_or_a_week_old_and_a_week_digest_exists(tmp_path):
    store = Store(tmp_path)
    living = tmp_path / "profile" / "living.md"
    assert living_profile_due(store, living, NOW) is False                         # no week digest yet: nothing to learn from
    store.write_card(Card(id="dgw_20261109", source="digest", type="thought", title="w", consumed_at=NOW,
                          topic=Topic(primary="uncertain"),
                          key_points=[KeyPoint(text="x", topic="uncertain", confidence=1.0)]))
    assert living_profile_due(store, living, NOW) is True                          # missing
    living.parent.mkdir(parents=True)
    living.write_text("# About\ntext", encoding="utf-8")
    assert living_profile_due(store, living, NOW) is False                         # fresh
    old = timelib.time() - 8 * 86400
    os.utime(living, (old, old))
    assert living_profile_due(store, living, NOW) is True                          # 8 days old


def test_sync_log_reports_digests_and_profile_status(tmp_path):
    settings = load_settings(root=tmp_path, env={})
    seed(tmp_path)
    empty = tmp_path / "projects"
    empty.mkdir()
    assert run_sync_command(settings, router_with(model), empty, 1, now=lambda: NOW) == 0
    line = (settings.raw_dir / "sync.log").read_text(encoding="utf-8").strip().splitlines()[-1]
    assert "digests: +1" in line and "profile: off" in line                        # off unless SB_LIVING_PROFILE=on
    assert Store(tmp_path).has("dgd_20261118")


def test_sync_without_a_local_model_skips_digests_and_does_not_fail(tmp_path):
    from secondbrain.llm import SensitivityError

    class Cloud:
        is_local, name = False, "cloud"

        def complete(self, prompt, *, system=None):
            raise AssertionError("private notes must never go to a cloud model")

    p = Cloud()
    settings = load_settings(root=tmp_path, env={})
    seed(tmp_path)
    empty = tmp_path / "projects"
    empty.mkdir()
    code = run_sync_command(settings, Router({"triage": p, "extract": p, "synthesis": p}), empty, 1, now=lambda: NOW)
    line = (settings.raw_dir / "sync.log").read_text(encoding="utf-8").strip().splitlines()[-1]
    assert "digests: skipped (no local model)" in line and not Store(tmp_path).has("dgd_20261118")
    assert code == 2  # exit code comes from the existing sessions/chats steps (no local model); digests add nothing to it
