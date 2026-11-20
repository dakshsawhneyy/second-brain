import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from secondbrain.datasync import DataSyncError, mirror, sync_data_repo

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)


def git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True).stdout


@pytest.fixture
def setup(tmp_path: Path):
    root = tmp_path / "brain"
    (root / "cards" / "2026" / "11").mkdir(parents=True)
    (root / "profile").mkdir()
    (root / "cards" / "2026" / "11" / "a.json").write_text('{"id": "a", "channel": null}', encoding="utf-8")
    (root / "cards" / "2026" / "11" / "secret.json").write_text('{"id": "s", "channel": "local-only"}', encoding="utf-8")
    (root / "cards" / "2026" / "11" / "broken.json").write_text("{not json", encoding="utf-8")
    (root / "profile" / "profile.md").write_text("about me", encoding="utf-8")
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "--bare", str(remote))
    repo = tmp_path / "data"
    git(tmp_path, "init", str(repo))
    git(repo, "config", "user.email", "t@t")
    git(repo, "config", "user.name", "t")
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "checkout", "-b", "main")
    return root, repo, remote


def test_mirror_copies_everything_including_private_entries(setup):
    root, repo, _ = setup
    mirror(root, repo)
    assert (repo / "cards/2026/11/a.json").is_file() and (repo / "profile/profile.md").is_file()
    assert (repo / "cards/2026/11/secret.json").is_file() and (repo / "cards/2026/11/broken.json").is_file()


def test_first_sync_pushes_then_no_changes_then_deletions_follow(setup):
    root, repo, remote = setup
    assert sync_data_repo(root, repo, NOW) == "ok (pushed)"
    assert "sync 2026-11-20" in git(remote, "log", "--format=%s", "main")
    assert sync_data_repo(root, repo, NOW) == "ok (no changes)"
    (root / "cards/2026/11/a.json").unlink()
    assert sync_data_repo(root, repo, NOW) == "ok (pushed)"
    assert "a.json" not in git(remote, "ls-tree", "-r", "--name-only", "main")
    assert "secret.json" in git(remote, "ls-tree", "-r", "--name-only", "main")


def test_failed_push_is_retried_next_run(setup, tmp_path):
    root, repo, remote = setup
    sync_data_repo(root, repo, NOW)
    (root / "cards/2026/11/b.json").write_text('{"id": "b"}', encoding="utf-8")
    git(repo, "remote", "set-url", "origin", str(tmp_path / "missing.git"))
    with pytest.raises(DataSyncError):
        sync_data_repo(root, repo, NOW)
    git(repo, "remote", "set-url", "origin", str(remote))
    assert sync_data_repo(root, repo, NOW) == "ok (pushed)"
    assert "b.json" in git(remote, "ls-tree", "-r", "--name-only", "main")


def test_not_a_git_repo_is_an_error(tmp_path):
    with pytest.raises(DataSyncError):
        sync_data_repo(tmp_path, tmp_path / "nope", NOW)
