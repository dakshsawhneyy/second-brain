"""`sb` command line interface: export-batch, ingest, search, bot."""

from __future__ import annotations

import argparse
import json
import os
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


def run_eval_command(settings: Settings, embedder: Embedder, out: Callable[[str], None] = print) -> int:
    """Does the search put the right note in the top results? Local only, uses no Claude quota."""
    from .advisor import CONTEXT_SOURCES
    from .evals import load_questions, run_eval

    try:
        questions = load_questions(settings.evals_path)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if not questions:
        out(f"no eval questions yet ({settings.evals_path}). Draft some with: sb eval --suggest 25")
        return 0
    index = Index(settings.index_path, embedder)
    result = run_eval(questions, lambda q, k: [h.card_id for h in index.search(q, k=k, per_source_cap=k,
                                                                                sources=CONTEXT_SOURCES)])  # as /ask sees it
    out(f"questions: {len(questions)}   recall@5: {result.recall_at_5:.2f}   recall@10: {result.recall_at_10:.2f}   "
        f"MRR: {result.mrr:.2f}")
    out("misses: " + (", ".join(result.misses) if result.misses else "none"))
    return 0


def run_eval_suggest_command(settings: Settings, llm, n: int, out: Callable[[str], None] = print) -> int:
    """Draft eval questions from his notes with the local model and merge them into the questions file."""
    from .evals import load_questions, suggest_questions

    try:
        existing = load_questions(settings.evals_path)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    taken = {q.id for q in existing}
    fresh = [q for q in suggest_questions(Store(settings.root), llm, n) if q.id not in taken]
    merged = existing + fresh
    settings.evals_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = settings.evals_path.with_name(settings.evals_path.name + ".tmp")
    tmp.write_text(json.dumps([q.model_dump() for q in merged], indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, settings.evals_path)
    out(f"added {len(fresh)} draft questions to {settings.evals_path} ({len(merged)} in total)")
    out("These are a smoke test only: a local model wrote them from your own notes. Edit them, and add about five "
        "of your own later for a real measure.")
    return 0


def _local_model(router: Router):
    """The local model for private work, or None when none is configured (private notes never go to a cloud model)."""
    try:
        return router.route("triage", "private")
    except (ConfigError, SensitivityError, KeyError):
        return None


def _update_profile(settings: Settings, llm, now: datetime) -> bool:
    from .digest import update_living_profile

    return update_living_profile(Store(settings.root), _read_text(settings.goals_path), llm, now, settings.profile_path,
                                 settings.onboarding_profile_path, settings.living_profile_path)


def run_digest_command(settings: Settings, llm, now: datetime, out: Callable[[str], None] = print,
                       max_calls: int = 20, force_profile: bool = False) -> int:
    """Create or update the day/week/month digests (local model), and the living profile when due or forced."""
    from .digest import living_profile_due, refresh_digests

    store = Store(settings.root)
    run = refresh_digests(store, llm, now, max_calls=max_calls)
    out(f"digests: created {len(run.created)}, up to date {run.skipped}, failed {run.failed}")
    living_on = settings.env.get("SB_LIVING_PROFILE", "off").strip().lower() == "on"
    if force_profile or (living_on and living_profile_due(store, settings.living_profile_path, now)):
        out("profile: " + ("updated" if _update_profile(settings, llm, now) else "not updated (kept the previous one)"))
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
    llm = _local_model(router)
    if llm is None:
        lines.append("digests: skipped (no local model)")
    else:
        try:  # a failing digest step must never fail the sync or hide in the log
            from .digest import living_profile_due, refresh_digests

            sync_store = Store(settings.root)
            run = refresh_digests(sync_store, llm, now(), max_calls=6)
            lines.append(f"digests: +{len(run.created)}" + (f" failed={run.failed}" if run.failed else ""))
            if settings.env.get("SB_LIVING_PROFILE", "off").strip().lower() != "on":
                lines.append("profile: off")  # it replaces the profile Claude reads: only when he switches it on
            elif living_profile_due(sync_store, settings.living_profile_path, now()):
                lines.append("profile: " + ("ok" if _update_profile(settings, llm, now()) else "failed"))
            else:
                lines.append("profile: skipped")
        except Exception as e:
            lines.append(f"digests: failed ({type(e).__name__})")
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

    ev = sub.add_parser("eval", help="check that search finds the right notes (recall, MRR); no Claude quota")
    ev.add_argument("--suggest", type=int, default=None, metavar="N", help="draft N questions from your notes first")

    dg = sub.add_parser("digest", help="build day/week/month digests of your notes with the local model")
    dg.add_argument("--profile", action="store_true", help="also rewrite the living profile now")

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
        if args.command == "eval":
            if args.suggest:
                code = run_eval_suggest_command(settings, build_router(settings.env).route("triage", "private"), args.suggest)
                if code != 0:
                    return code
            return run_eval_command(settings, _default_embedder(settings))
        if args.command == "digest":
            llm = _local_model(build_router(settings.env))
            if llm is None:
                print("error: no local model configured (set SB_OLLAMA_MODEL in .env)", file=sys.stderr)
                return 2
            return run_digest_command(settings, llm, datetime.now().astimezone(), force_profile=args.profile)
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

            from .netfix import prefer_ipv4

            prefer_ipv4()  # his IPv6 route to Telegram fails about half the time; IPv4 does not
            from .inbox import Inbox
            from .outbox import Outbox
            from .speech import WhisperTranscriber

            transcriber = (None if settings.env.get("SB_VOICE", "on").strip().lower() == "off" else
                           WhisperTranscriber(settings.env.get("SB_WHISPER_MODEL", "").strip() or "small",
                                              settings.env.get("SB_WHISPER_LANG", "").strip() or None,
                                              settings.raw_dir / "models" / "whisper"))

            def serve() -> None:  # a fresh Application AND event loop per attempt (run_polling closes its loop)
                import asyncio

                asyncio.set_event_loop(asyncio.new_event_loop())
                build_application(settings.telegram_token, settings.owner_telegram_id, store, goals,
                                  settings.raw_dir / "bot_state.json",
                                  focus_projects=focus, classifier=classifier,
                                  index=Index(settings.index_path, _default_embedder(settings)),
                                  mentor=mentor, transcriber=transcriber,
                                  inbox=Inbox(settings.raw_dir / "inbox.json"),
                                  outbox=Outbox(settings.raw_dir / "outbox.json")).run_polling(bootstrap_retries=-1)  # keep retrying while offline

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
