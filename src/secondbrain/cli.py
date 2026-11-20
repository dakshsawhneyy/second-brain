"""`sb` command line interface: export-batch, ingest, search, bot."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

from .adapters.takeout import WatchItem, parse_takeout
from .config import Settings, load_settings
from .embed import DEFAULT_OLLAMA_EMBED_MODEL, DEFAULT_OLLAMA_URL, Embedder, FastEmbedder, OllamaEmbedder
from . import usage
from .index import Index
from .llm import ConfigError, Router, SensitivityError, build_router
from .pipeline import run_ingest
from .store import Store
from .transcripts import RateLimited, Transcript, TranscriptError, get_transcript, to_text


def export_batch(
    items: Sequence[WatchItem],
    n: int,
    out: Path,
    cache_dir: Path,
    fetch: Callable[[str, Path], Transcript | None] = get_transcript,
) -> list[Path]:
    """Write up to n transcripts of mixed lengths (shortest..longest) plus manifest.json.

    Fetches at most 3*n transcripts so we stay polite to YouTube.
    """
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)

    candidates: list[tuple[WatchItem, Transcript, str]] = []
    for item in list(items)[: 3 * n]:
        try:
            t = fetch(item.video_id, cache_dir)
        except RateLimited:
            break  # YouTube is throttling us: keep what we have, stop asking
        except TranscriptError:
            continue  # this one video cannot be read: skip it
        if t is None or not t.segments:
            continue
        candidates.append((item, t, to_text(t, with_times=True)))

    candidates.sort(key=lambda c: len(c[2]))
    if len(candidates) > n:
        if n == 1:
            picks = [len(candidates) // 2]
        else:
            last = len(candidates) - 1
            picks = [round(i * last / (n - 1)) for i in range(n)]
        candidates = [candidates[i] for i in picks]

    paths: list[Path] = []
    manifest: list[dict] = []
    for item, t, text in candidates:
        path = out / f"{item.video_id}.txt"
        path.write_text(text, encoding="utf-8")
        paths.append(path)
        manifest.append({
            "video_id": item.video_id,
            "title": item.title,
            "minutes": round(t.segments[-1].start / 60, 1),
            "chars": len(text),
        })
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return paths


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def run_ingest_command(
    settings: Settings,
    takeout: Path,
    limit: int | None,
    router: Router,
    embedder: Embedder,
    fetch: Callable[[str, Path], Transcript | None] = get_transcript,
    out: Callable[[str], None] = print,
) -> int:
    try:
        items = parse_takeout(takeout)
    except (ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    goals = _read_text(settings.goals_path)
    if not goals:
        out(f"warning: {settings.goals_path} not found or empty; triage will score without your goals")

    store = Store(settings.root)
    try:
        with usage.section("ingest"):
            report = run_ingest(items, store, router, goals, settings.raw_dir, fetch=fetch, limit=limit)
    except SensitivityError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    indexed = Index(settings.index_path, embedder).rebuild(store)
    out(f"ingest: new_cards={report.new_cards} tombstones={report.tombstones} "
        f"skipped_existing={report.skipped_existing} failures={len(report.failures)} indexed={indexed}")
    for card_id, message in report.failures:
        out(f"  failed {card_id}: {message}")
    return 0


def run_search_command(settings: Settings, query: str, embedder: Embedder, k: int = 5,
                       out: Callable[[str], None] = print) -> int:
    hits = Index(settings.index_path, embedder).search(query, k=k)
    if not hits:
        out("no results")
        return 0
    for hit in hits:
        out(f"{hit.score:.2f}  [{hit.card_id}] {hit.title}")
        if hit.snippet:
            out(f"      {hit.snippet}")
    return 0


def default_projects_dir() -> Path:
    return Path.home() / ".claude" / "projects"


def run_sessions_command(settings: Settings, router: Router, projects_dir: Path, limit: int | None,
                         out: Callable[[str], None] = print) -> int:
    """Summarise Claude Code sessions into private cards. The router refuses a non-local model for private data."""
    from .sessions import import_sessions

    if not projects_dir.is_dir():
        print(f"error: {projects_dir} is not a folder", file=sys.stderr)
        return 2
    try:
        llm = router.route("triage", "private")  # triage is local-only by design
    except SensitivityError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    store = Store(settings.root)
    with usage.section("sync.sessions"):
        res = import_sessions(projects_dir, store, settings.raw_dir / "sessions_state.json", llm, limit=limit)
    out(f"sessions: imported={res.imported} failed={res.failed} unchanged={res.skipped_unchanged} "
        f"active={res.skipped_active} trivial={res.skipped_trivial}")
    return 0 if res.failed == 0 else 1


def run_chats_command(settings: Settings, router: Router, drop_dir: Path, limit: int | None,
                      out: Callable[[str], None] = print) -> int:
    """Summarise a claude.ai data export (dropped in raw/claude-chats/) into private cards, locally."""
    from .claude_chats import import_chats

    try:
        llm = router.route("triage", "private")
    except SensitivityError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    with usage.section("sync.chats"):
        res = import_chats(drop_dir, Store(settings.root), settings.raw_dir / "chats_state.json", llm, limit=limit)
    out(f"chats: imported={res.imported} failed={res.failed} unchanged={res.skipped_unchanged} "
        f"trivial={res.skipped_trivial}")
    return 0 if res.failed == 0 else 1


def run_index_command(settings: Settings, embedder: Embedder, out: Callable[[str], None] = print) -> int:
    with usage.section("sync.index"):
        added, removed, total = Index(settings.index_path, embedder).update(Store(settings.root))
    out(f"index: +{added} -{removed} ={total}")
    return 0


def run_backup_command(settings: Settings, now: datetime, out: Callable[[str], None] = print) -> int:
    from .backup import BackupError, make_backup

    dest = Path(settings.env.get("SB_BACKUP_DIR", "").strip() or settings.root / "backups")
    try:
        path = make_backup(settings.root, dest, settings.env.get("SB_BACKUP_PASSPHRASE", "").strip() or None, now)
    except BackupError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    out(f"backup: wrote {path}")
    return 0


def run_restore_command(settings: Settings, backup: Path, target: Path, out: Callable[[str], None] = print) -> int:
    from .backup import BackupError, restore_backup

    try:
        n = restore_backup(backup, settings.env.get("SB_BACKUP_PASSPHRASE", "").strip(), target)
    except (BackupError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    out(f"restore: {n} files into {target}")
    return 0


def run_sync_command(settings: Settings, router: Router, projects_dir: Path, limit: int | None,
                     now: Callable[[], datetime] = lambda: datetime.now().astimezone(),
                     embedder: Embedder | None = None) -> int:
    """Scheduled job: sessions, chats, index, backup. One summary line is appended to raw/sync.log (no console)."""
    from .backup import backed_up_today, make_backup

    lines: list[str] = []
    codes = [run_sessions_command(settings, router, projects_dir, limit, out=lines.append),
             run_chats_command(settings, router, settings.raw_dir / "claude-chats", limit, out=lines.append)]
    if embedder is not None:
        try:
            run_index_command(settings, embedder, out=lines.append)
        except Exception as e:  # a broken index must not stop the backup or hide in the log
            lines.append(f"index: failed ({type(e).__name__})")
            codes.append(1)
    dest = Path(settings.env.get("SB_BACKUP_DIR", "").strip() or settings.root / "backups")
    passphrase = settings.env.get("SB_BACKUP_PASSPHRASE", "").strip()
    data_repo = settings.env.get("SB_DATA_REPO", "").strip()
    if data_repo:  # plain-text mirror in his separate private repo, pushed automatically (approved 2026-11-20)
        from .datasync import DataSyncError, sync_data_repo

        try:
            lines.append("data: " + sync_data_repo(settings.root, Path(data_repo), now()))
        except (DataSyncError, OSError) as e:
            lines.append(f"data: failed ({e})")  # its own alert; not a failed sync
    if not passphrase:
        if not data_repo:
            lines.append("backup: not set up")
    elif backed_up_today(dest, now()):
        lines.append("backup: ok (today)")
    else:
        try:
            make_backup(settings.root, dest, passphrase, now())
            lines.append("backup: ok")
        except Exception as e:
            lines.append(f"backup: failed ({type(e).__name__})")
            codes.append(1)
    settings.raw_dir.mkdir(parents=True, exist_ok=True)
    with (settings.raw_dir / "sync.log").open("a", encoding="utf-8") as fh:
        fh.write(f"{now().isoformat(timespec='seconds')} | " + " | ".join(lines) + f" | exit={max(codes)}\n")
    return max(codes)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sb", description="Second brain")
    sub = parser.add_subparsers(dest="command", required=True)

    eb = sub.add_parser("export-batch", help="export a mixed-length batch of transcripts for the Claude usage experiment")
    eb.add_argument("--takeout", type=Path, required=True, help="path to Takeout watch-history.json")
    eb.add_argument("--n", type=int, default=10)
    eb.add_argument("--out", type=Path, default=None, help="output folder (default: raw/experiment)")

    ing = sub.add_parser("ingest", help="turn a Takeout watch history into memory cards and rebuild the index")
    ing.add_argument("--takeout", type=Path, required=True)
    ing.add_argument("--limit", type=int, default=None, help="stop after this many new items")

    se = sub.add_parser("search", help="search the memory")
    se.add_argument("query")
    se.add_argument("--k", type=int, default=5)

    ss = sub.add_parser("sessions", help="summarise Claude Code sessions into private cards (local model, no Claude quota)")
    ss.add_argument("--limit", type=int, default=None, help="summarise at most this many sessions this run")
    ss.add_argument("--projects-dir", type=Path, default=None, help="default: ~/.claude/projects")

    ch = sub.add_parser("chats", help="summarise a claude.ai data export dropped in raw/claude-chats/ (local model)")
    ch.add_argument("--limit", type=int, default=None)

    sy = sub.add_parser("sync", help="scheduled job: sessions + chats, logs to raw/sync.log")
    sy.add_argument("--limit", type=int, default=3, help="summaries per source per run (default 3)")
    sy.add_argument("--projects-dir", type=Path, default=None)

    us = sub.add_parser("usage", help="Claude and local model calls per section, from raw/usage.jsonl")
    us.add_argument("--days", type=int, default=7)

    sub.add_parser("index", help="update the search index with new and changed cards")
    sub.add_parser("backup", help="write an encrypted backup of cards/archive/profile (needs SB_BACKUP_PASSPHRASE)")
    rs = sub.add_parser("restore", help="decrypt a backup into an empty folder")
    rs.add_argument("--file", type=Path, required=True)
    rs.add_argument("--to", type=Path, required=True)

    sub.add_parser("bot", help="run the Telegram bot (morning brief, evening check-in, quick capture)")
    return parser


def _default_embedder(settings: Settings) -> Embedder:
    """Ollama's embedding model by default (already installed locally, no extra download site).

    SB_EMBEDDER=fastembed switches to the bge-small model, which downloads from Hugging Face.
    """
    if settings.env.get("SB_EMBEDDER", "ollama").strip().lower() == "fastembed":
        return FastEmbedder(cache_dir=settings.root / "index" / "models")
    return OllamaEmbedder(model=settings.env.get("SB_EMBED_MODEL", "").strip() or DEFAULT_OLLAMA_EMBED_MODEL,
                          base_url=settings.env.get("SB_OLLAMA_URL", "").strip() or DEFAULT_OLLAMA_URL)


def main(argv: Sequence[str] | None = None, settings: Settings | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = settings or load_settings()
    usage.configure(settings.raw_dir / "usage.jsonl")
    try:
        if args.command == "usage":
            print(usage.report_text(settings.raw_dir / "usage.jsonl", args.days))
            return 0
        if args.command == "export-batch":
            items = parse_takeout(args.takeout)
            out = args.out or settings.raw_dir / "experiment"
            paths = export_batch(items, args.n, out, settings.raw_dir)
            print(f"exported {len(paths)} transcripts to {out}")
            return 0
        if args.command == "ingest":
            router = build_router(settings.env)
            return run_ingest_command(settings, args.takeout, args.limit, router, _default_embedder(settings))
        if args.command == "sessions":
            router = build_router(settings.env)
            return run_sessions_command(settings, router, args.projects_dir or default_projects_dir(), args.limit)
        if args.command == "chats":
            return run_chats_command(settings, build_router(settings.env), settings.raw_dir / "claude-chats", args.limit)
        if args.command == "sync":
            return run_sync_command(settings, build_router(settings.env), args.projects_dir or default_projects_dir(),
                                    args.limit, embedder=_default_embedder(settings))
        if args.command == "index":
            return run_index_command(settings, _default_embedder(settings))
        if args.command == "backup":
            return run_backup_command(settings, datetime.now().astimezone())
        if args.command == "restore":
            return run_restore_command(settings, args.file, args.to)
        if args.command == "search":
            return run_search_command(settings, args.query, _default_embedder(settings), k=args.k)
        if args.command == "bot":
            if not settings.telegram_token:
                print("error: SB_TELEGRAM_TOKEN is not set (put it in .env)", file=sys.stderr)
                return 2
            if settings.owner_telegram_id is None:
                print("error: SB_OWNER_TELEGRAM_ID is not set (put it in .env)", file=sys.stderr)
                return 2
            from .bot.app import build_application, configure_logging, run_with_retries

            configure_logging(log_file=settings.raw_dir / "bot.log", token=settings.telegram_token)
            store = Store(settings.root)
            goals = _read_text(settings.goals_path)
            focus_file = settings.root / "profile" / "focus-projects.txt"
            focus = tuple(line.strip() for line in _read_text(focus_file).splitlines()
                          if line.strip() and not line.startswith("#")) or None

            classifier = None
            try:
                from .bot.classify import classify_text

                label_llm = build_router(settings.env).route("triage", "private")  # local-only by design
                classifier = lambda text: classify_text(text, label_llm)  # noqa: E731
            except (ConfigError, SensitivityError):
                pass  # no local model configured: messages stay plain thoughts

            mentor = None
            if settings.env.get("SB_MENTOR", "on").strip().lower() != "off" and classifier is not None:
                from .advisor import claude_cli_runner
                from .mentor.flow import Mentor

                search_index = Index(settings.index_path, _default_embedder(settings))
                mentor = Mentor(store, settings.raw_dir / "mentor_state.json", claude_cli_runner, local_llm=label_llm,
                                goals_text=goals, profile_path=settings.profile_path, index=search_index)

            def serve() -> None:  # a fresh Application AND event loop per attempt (run_polling closes its loop)
                import asyncio

                asyncio.set_event_loop(asyncio.new_event_loop())
                build_application(settings.telegram_token, settings.owner_telegram_id, store, goals,
                                  settings.raw_dir / "bot_state.json",
                                  focus_projects=focus, classifier=classifier,
                                  index=Index(settings.index_path, _default_embedder(settings)),
                                  mentor=mentor).run_polling(bootstrap_retries=-1)  # keep retrying while offline

            code = run_with_retries(serve, settings.telegram_token)
            if code == 2:
                print("error: Telegram rejected the bot token (check SB_TELEGRAM_TOKEN)", file=sys.stderr)
            return code
    except (ConfigError, ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
