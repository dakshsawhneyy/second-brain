from pathlib import Path

from secondbrain.config import load_settings


def test_load_settings_defaults_paths_under_root(tmp_path: Path):
    s = load_settings(root=tmp_path, env={})
    assert s.root == tmp_path
    assert s.cards_dir == tmp_path / "cards"
    assert s.archive_dir == tmp_path / "archive"
    assert s.raw_dir == tmp_path / "raw"
    assert s.index_path == tmp_path / "index" / "brain.db"
    assert s.profile_path == tmp_path / "profile" / "profile.md"
    assert s.goals_path == tmp_path / "profile" / "goals.md"


def test_owner_id_parsed_from_env(tmp_path: Path):
    s = load_settings(root=tmp_path, env={"SB_OWNER_TELEGRAM_ID": "123"})
    assert s.owner_telegram_id == 123


def test_token_never_appears_in_repr_or_str(tmp_path: Path):
    s = load_settings(root=tmp_path, env={"SB_TELEGRAM_TOKEN": "123456:SECRET-TOKEN", "SB_GROQ_API_KEY": "gsk-SECRET"})
    assert "SECRET" not in repr(s) and "SECRET" not in str(s)
    assert s.telegram_token == "123456:SECRET-TOKEN"


def test_missing_token_is_none(tmp_path: Path):
    s = load_settings(root=tmp_path, env={})
    assert s.telegram_token is None
    assert s.owner_telegram_id is None


def test_dotenv_file_is_read_when_env_not_given(tmp_path: Path):
    (tmp_path / ".env").write_text("SB_OWNER_TELEGRAM_ID=77\nSB_TELEGRAM_TOKEN=abc\n", encoding="utf-8")
    s = load_settings(root=tmp_path)
    assert s.owner_telegram_id == 77
    assert s.telegram_token == "abc"
