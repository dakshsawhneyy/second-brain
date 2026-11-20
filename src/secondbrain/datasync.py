"""Mirror the memory (cards, archive, profile) into a separate private git repo and push it.

The code repo never holds his data (cards/, archive/, profile/ are gitignored there). This module copies those
folders into the data repo, everything including /private entries (approved by him 2026-11-20; `local-only` only
keeps them out of Claude context packs, not out of his own private repo), then commits and pushes only if something changed. A failed push keeps the commit locally; the next run pushes it.
"""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime
from pathlib import Path

FOLDERS = ("cards", "archive", "profile")
README = ("# Second brain data\n\nWritten automatically by the second-brain sync job. Do not edit by hand: "
          "changes here are overwritten.\nEntries saved with /private are never copied here.\n")
GIT_TIMEOUT = 120


class DataSyncError(Exception):
    pass


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["git", "-c", "core.autocrlf=false", *args], cwd=repo, capture_output=True, text=True,
                              timeout=GIT_TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise DataSyncError(type(e).__name__) from e


def _wanted(root: Path, folder: str) -> dict[str, Path]:
    base = root / folder
    out: dict[str, Path] = {}
    if not base.is_dir():
        return out
    for path in base.rglob("*"):
        if not path.is_file() or path.name.endswith(".tmp"):
            continue
        out[path.relative_to(root).as_posix()] = path
    return out


def mirror(root: Path, repo: Path) -> int:
    """Make the data repo's folders match the source. Returns files written or removed."""
    changed = 0
    for folder in FOLDERS:
        wanted = _wanted(Path(root), folder)
        target = Path(repo) / folder
        if target.is_dir():
            for existing in list(target.rglob("*")):
                if existing.is_file() and existing.relative_to(repo).as_posix() not in wanted:
                    existing.unlink()
                    changed += 1
        for rel, src in wanted.items():
            dest = Path(repo) / rel
            data = src.read_bytes()
            if dest.is_file() and dest.read_bytes() == data:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            changed += 1
        if target.is_dir():  # tidy now-empty month folders
            for d in sorted((p for p in target.rglob("*") if p.is_dir()), reverse=True):
                if not any(d.iterdir()):
                    shutil.rmtree(d, ignore_errors=True)
    readme = Path(repo) / "README.md"
    if not readme.is_file() or readme.read_text(encoding="utf-8") != README:
        readme.write_text(README, encoding="utf-8")
        changed += 1
    return changed


def sync_data_repo(root: Path, repo: Path, now: datetime) -> str:
    """Mirror, commit and push. Returns a short status: 'ok (no changes)', 'ok (pushed)' ... Raises DataSyncError."""
    repo = Path(repo)
    if not (repo / ".git").exists():
        raise DataSyncError("not a git repo")
    mirror(Path(root), repo)
    _git(repo, "add", "-A")
    pending = _git(repo, "status", "--porcelain")
    if pending.returncode != 0:
        raise DataSyncError("git status")
    if pending.stdout.strip():
        commit = _git(repo, "commit", "-m", f"sync {now.isoformat(timespec='minutes')}")
        if commit.returncode != 0:
            raise DataSyncError("git commit")
    ahead = _git(repo, "rev-list", "--count", "@{u}..HEAD")  # also catches a commit whose push failed last time
    if ahead.returncode != 0:
        push = _git(repo, "push", "-u", "origin", "HEAD")  # first push sets the upstream
    elif ahead.stdout.strip() not in ("", "0"):
        push = _git(repo, "push")
    else:
        return "ok (no changes)"
    if push.returncode != 0:
        raise DataSyncError("git push")
    return "ok (pushed)"
