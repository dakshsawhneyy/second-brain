import json
from pathlib import Path

import pytest

from secondbrain.cli import main, run_ingest_command, run_search_command
from secondbrain.config import load_settings
from secondbrain.embed import HashEmbedder
from secondbrain.llm import Router
from secondbrain.store import Store
from secondbrain.transcripts import Segment, Transcript

FIXTURE = Path(__file__).parent / "fixtures" / "watch-history.json"


class FnProvider:
    def __init__(self, fn):
        self.fn, self.is_local, self.name = fn, True, "fake"

    def complete(self, prompt, *, system=None):
        return self.fn(prompt)


def triage_fn(prompt: str) -> str:
    entertainment = "Hindi" in prompt or "हिंदी" in prompt
    topic = "noise/entertainment" if entertainment else "infra/cloud"
    return json.dumps({"topic": topic, "format": "tutorial", "bet_job": 9, "bet_product": 3,
                       "actionability": 7, "novelty": 6, "quality": 8})


def extract_fn(prompt: str) -> str:
    return json.dumps({"key_points": [{"text": "services route traffic", "topic": "infra/cloud", "t": "00:10", "confidence": 0.9}],
                       "action": "Try kubectl port-forward"})


def fake_router() -> Router:
    return Router({"triage": FnProvider(triage_fn), "extract": FnProvider(extract_fn), "synthesis": FnProvider(extract_fn)})


def fetch(video_id: str, cache_dir: Path):
    return Transcript(video_id=video_id, language="en", segments=[Segment(0.0, "hello"), Segment(10.0, "world")])


def summary(lines: list[str]) -> str:
    return next(line for line in lines if line.startswith("ingest:"))


def test_ingest_command_end_to_end_with_fake_providers(tmp_path: Path):
    settings = load_settings(root=tmp_path, env={})
    out: list[str] = []
    code = run_ingest_command(settings, FIXTURE, limit=None, router=fake_router(), embedder=HashEmbedder(), fetch=fetch, out=out.append)
    assert code == 0
    assert "new_cards=1" in summary(out) and "tombstones=1" in summary(out) and "skipped_existing=0" in summary(out)
    cards = list(Store(tmp_path).iter_cards())
    assert [c.title for c in cards] == ["Kubernetes Networking Explained"]
    assert settings.index_path.is_file()

    hits: list[str] = []
    assert run_search_command(settings, "kubernetes networking", embedder=HashEmbedder(), out=hits.append) == 0
    assert any("Kubernetes Networking Explained" in h for h in hits)

    again: list[str] = []
    run_ingest_command(settings, FIXTURE, limit=None, router=fake_router(), embedder=HashEmbedder(), fetch=fetch, out=again.append)
    assert "new_cards=0" in summary(again) and "skipped_existing=2" in summary(again)


def test_ingest_reports_failures_and_still_exits_zero(tmp_path: Path):
    settings = load_settings(root=tmp_path, env={})
    router = Router({"triage": FnProvider(lambda p: "garbage"), "extract": FnProvider(extract_fn), "synthesis": FnProvider(extract_fn)})
    out: list[str] = []
    code = run_ingest_command(settings, FIXTURE, limit=None, router=router, embedder=HashEmbedder(), fetch=fetch, out=out.append)
    assert code == 0 and "failures=2" in summary(out)
    assert any("yt_aaaaaaaaaaa" in line for line in out[1:])


def test_ingest_missing_takeout_file_exits_2_with_message(tmp_path: Path, capsys):
    settings = load_settings(root=tmp_path, env={})
    code = run_ingest_command(settings, tmp_path / "nope.json", limit=None, router=fake_router(), embedder=HashEmbedder(), fetch=fetch, out=print)
    assert code == 2 and "nope.json" in capsys.readouterr().err


def test_ingest_with_bad_routing_config_exits_2_without_leaking_secrets(tmp_path: Path, capsys):
    env = {"SB_ROUTE_EXTRACT": "groq", "SB_GROQ_API_KEY": "sk-SECRET", "SB_OLLAMA_MODEL": "m"}
    code = main(["ingest", "--takeout", str(FIXTURE)], settings=load_settings(root=tmp_path, env=env))
    captured = capsys.readouterr()
    assert code == 2 and "SB_GROQ_MODEL" in captured.err
    assert "sk-SECRET" not in captured.err + captured.out


def test_ingest_limit_is_passed_through(tmp_path: Path):
    settings = load_settings(root=tmp_path, env={})
    out: list[str] = []
    run_ingest_command(settings, FIXTURE, limit=1, router=fake_router(), embedder=HashEmbedder(), fetch=fetch, out=out.append)
    assert "new_cards=1" in summary(out) and "tombstones=0" in summary(out)


def test_goals_file_is_used_when_present_and_warning_when_missing(tmp_path: Path):
    settings = load_settings(root=tmp_path, env={})
    out: list[str] = []
    run_ingest_command(settings, FIXTURE, limit=1, router=fake_router(), embedder=HashEmbedder(), fetch=fetch, out=out.append)
    assert any("goals.md" in line for line in out)  # warns that goals are missing
    (tmp_path / "profile").mkdir()
    (tmp_path / "profile" / "goals.md").write_text("Focus: infra", encoding="utf-8")
    out2: list[str] = []
    run_ingest_command(settings, FIXTURE, limit=2, router=fake_router(), embedder=HashEmbedder(), fetch=fetch, out=out2.append)
    assert not any("goals.md" in line for line in out2)


def test_search_with_no_index_says_so(tmp_path: Path):
    out: list[str] = []
    assert run_search_command(load_settings(root=tmp_path, env={}), "anything", embedder=HashEmbedder(), out=out.append) == 0
    assert any("no results" in line.lower() for line in out)


def test_bot_command_requires_token_and_owner(tmp_path: Path, capsys):
    assert main(["bot"], settings=load_settings(root=tmp_path, env={})) == 2
    assert "SB_TELEGRAM_TOKEN" in capsys.readouterr().err
    assert main(["bot"], settings=load_settings(root=tmp_path, env={"SB_TELEGRAM_TOKEN": "123456:abc"})) == 2
    assert "SB_OWNER_TELEGRAM_ID" in capsys.readouterr().err


def test_bot_command_runs_the_app_through_the_retry_wrapper(tmp_path: Path, monkeypatch):
    import secondbrain.bot.app as botapp

    ran: list[str] = []

    class FakeApp:
        def run_polling(self, **kwargs):
            ran.append("polled")

    monkeypatch.setattr(botapp, "build_application", lambda *a, **k: FakeApp())
    monkeypatch.setattr(botapp, "configure_logging", lambda **k: None)
    settings = load_settings(root=tmp_path, env={"SB_TELEGRAM_TOKEN": "123456:abc", "SB_OWNER_TELEGRAM_ID": "42"})
    assert main(["bot"], settings=settings) == 0 and ran == ["polled"]


def test_parser_has_ingest_search_bot_commands():
    from secondbrain.cli import build_parser

    p = build_parser()
    assert p.parse_args(["ingest", "--takeout", "t.json", "--limit", "5"]).limit == 5
    assert p.parse_args(["search", "hello world"]).query == "hello world"
    assert p.parse_args(["bot"]).command == "bot"


def test_retry_survives_a_closed_event_loop_error():
    from secondbrain.bot.app import run_with_retries

    calls = {"n": 0}

    def run():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("Event loop is closed")

    assert run_with_retries(run, "123456:abc", sleep=lambda s: None) == 0 and calls["n"] == 2


def test_retry_survives_any_unexpected_crash_and_still_stops_on_bad_token():
    from telegram.error import InvalidToken
    from secondbrain.bot.app import run_with_retries

    calls = {"n": 0}

    def run():
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("something unexpected")

    assert run_with_retries(run, "123456:abc", sleep=lambda s: None) == 0 and calls["n"] == 2

    def bad():
        raise InvalidToken("nope")

    assert run_with_retries(bad, "123456:abc", sleep=lambda s: None) == 2


def _eval_setup(tmp_path):
    import json as _json
    from datetime import datetime, timezone
    from secondbrain.index import Index
    from secondbrain.schema import Card, KeyPoint, Topic

    settings = load_settings(root=tmp_path, env={})
    store = Store(settings.root)
    for cid, text in (("tg_a", "kubernetes networking and services explained for beginners"),
                      ("tg_b", "terraform modules split state per environment for safety")):
        store.write_card(Card(id=cid, source="telegram", type="thought", title=text[:40],
                              consumed_at=datetime(2026, 11, 20, tzinfo=timezone.utc), topic=Topic(primary="uncertain"),
                              key_points=[KeyPoint(text=text, topic="uncertain", confidence=1.0)]))
    Index(settings.index_path, HashEmbedder()).rebuild(store)
    settings.evals_path.parent.mkdir(parents=True, exist_ok=True)
    settings.evals_path.write_text(_json.dumps([
        {"id": "q1", "question": "kubernetes networking services", "expect_ids": ["tg_a"]},
        {"id": "q2", "question": "something about cooking pasta", "expect_ids": ["tg_b"]}]), encoding="utf-8")
    return settings


def test_eval_command_reports_recall_and_lists_misses(tmp_path):
    from secondbrain.cli import run_eval_command
    settings = _eval_setup(tmp_path)
    lines: list[str] = []
    assert run_eval_command(settings, HashEmbedder(), out=lines.append) == 0
    text = "\n".join(lines)
    assert "recall@5" in text and "MRR" in text and "q2" in text and "q1" not in text.split("misses")[-1]


def test_eval_command_without_questions_explains_how_to_start(tmp_path):
    from secondbrain.cli import run_eval_command
    settings = load_settings(root=tmp_path, env={})
    lines: list[str] = []
    assert run_eval_command(settings, HashEmbedder(), out=lines.append) == 0
    assert "--suggest" in "\n".join(lines)


def test_eval_command_with_a_corrupt_file_fails_clearly(tmp_path, capsys):
    from secondbrain.cli import run_eval_command
    settings = load_settings(root=tmp_path, env={})
    settings.evals_path.parent.mkdir(parents=True, exist_ok=True)
    settings.evals_path.write_text("{broken", encoding="utf-8")
    assert run_eval_command(settings, HashEmbedder(), out=lambda s: None) == 2
    assert "questions.json" in capsys.readouterr().err


def test_eval_suggest_merges_without_overwriting_and_prints_the_caveat(tmp_path):
    import json as _json
    from secondbrain.cli import run_eval_suggest_command
    settings = _eval_setup(tmp_path)
    existing = _json.loads(settings.evals_path.read_text(encoding="utf-8"))
    existing[0]["question"] = "MY OWN WORDING"
    settings.evals_path.write_text(_json.dumps(existing), encoding="utf-8")
    lines: list[str] = []
    llm = FnProvider(lambda prompt: _json.dumps({"question": "a drafted question"}))
    assert run_eval_suggest_command(settings, llm, 5, out=lines.append) == 0
    saved = {q["id"]: q for q in _json.loads(settings.evals_path.read_text(encoding="utf-8"))}
    assert saved["q1"]["question"] == "MY OWN WORDING"          # his own edit is never overwritten
    assert "smoke test" in "\n".join(lines)


def test_parser_has_eval_command():
    from secondbrain.cli import build_parser
    args = build_parser().parse_args(["eval", "--suggest", "12"])
    assert args.command == "eval" and args.suggest == 12
