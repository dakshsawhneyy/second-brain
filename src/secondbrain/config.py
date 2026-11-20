"""Settings: paths under the project root and values from .env / environment."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    root: Path
    cards_dir: Path
    archive_dir: Path
    raw_dir: Path
    index_path: Path
    profile_path: Path
    goals_path: Path
    evals_path: Path
    living_profile_path: Path
    onboarding_profile_path: Path
    owner_telegram_id: int | None
    telegram_token: str | None = field(repr=False)  # secret: never shown in repr/tracebacks
    env: Mapping[str, str] = field(default_factory=dict, repr=False)  # may hold secrets: hidden from repr


def _read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _default_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_settings(root: Path | None = None, env: Mapping[str, str] | None = None) -> Settings:
    root = Path(root) if root is not None else _default_root()
    if env is None:
        merged = _read_dotenv(root / ".env")
        merged.update({k: v for k, v in os.environ.items() if k.startswith("SB_")})
        env = merged
    owner_raw = env.get("SB_OWNER_TELEGRAM_ID", "").strip()
    return Settings(
        root=root,
        cards_dir=root / "cards",
        archive_dir=root / "archive",
        raw_dir=root / "raw",
        index_path=root / "index" / "brain.db",
        profile_path=root / "profile" / "profile.md",
        goals_path=root / "profile" / "goals.md",
        evals_path=root / "profile" / "evals" / "questions.json",  # his data folder: never in the code repo
        living_profile_path=root / "profile" / "living.md",
        onboarding_profile_path=root / "profile" / "onboarding.md",
        owner_telegram_id=int(owner_raw) if owner_raw.isdigit() else None,
        telegram_token=env.get("SB_TELEGRAM_TOKEN") or None,
        env=dict(env),
    )
