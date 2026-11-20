# Next steps (start here in the next session)

Last updated 2026-11-17. State of the build: see docs/PROJECT_STATE.md. All code for Stages 0b-2 is written and tested (266 tests).
Check items off by editing this file. Rules: free only, never touch SkipATS, no git add/commit/push without his approval each time.

## A. Needs internet (do in this order)
- [ ] 1. YouTube Takeout: takeout.google.com -> deselect all -> YouTube and YouTube Music -> history only, format JSON -> download.
        Save as `raw\takeout\watch-history.json`. (Google can take hours, so start it first.)
- [ ] 2. Pull the local model (resumes if interrupted; about 4.7 GB, his connection is about 2 MB/s):
        `& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" pull qwen2.5:7b`   (fallback: qwen2.5:3b, about 1.9 GB)
        Verify with `ollama list`, then set `SB_OLLAMA_MODEL=qwen2.5:7b` in `.env` (Claude can do this).
        Note: `ollama pull` can exit 0 even when the download aborted, so always check `ollama list`.
- [ ] 3. Regenerate the Telegram bot token in BotFather (/revoke, then /token). It was pasted in chat once. Update `SB_TELEGRAM_TOKEN` in `.env`.
- [ ] 4. Task 6, the Claude usage experiment (plan: docs/superpowers/plans/2026-11-17-second-brain-stage-0b-2.md, Task 6 steps 5-9; protocol: design.md Stage 0b):
        - `.\.venv\Scripts\python -m secondbrain.cli export-batch --takeout raw\takeout\watch-history.json --n 10`
        - Fresh Claude session: note usage readings, have Claude extract the 10 transcripts, read usage again, compute percent per video and per day.
        - Repeat once with a 3-file headless `claude -p` batch and see which pool moves (subscription limits or a separate credit pool).
        - Compare quality against the local model on the same batch; spot-check 5 extractions.
        - Write results in `docs/experiments/2026-claude-usage.md`, show him the numbers, then he chooses Plan A (Claude direct) or Plan B (routing table in design.md 5c).
        - Set `SB_ROUTE_*` in `.env` accordingly.
- [ ] 5. First real ingest: `.\.venv\Scripts\python -m secondbrain.cli ingest --takeout raw\takeout\watch-history.json --limit 100`
        Spot-check 20 cards (key points correct, topic right) -> write `docs/experiments/stage1-spot-check.md`. Tune scoring weights if needed.
- [ ] 6. Live bot check: run `sb bot` once (or log off and on so autostart runs), message the bot `idea: test`, check a card appears, press the buttons on `/brief`.
        Do not run the bot by hand while the autostart task is running (Telegram allows one poller per bot).
- [ ] 7. Start the 14-day stop-rule clock. Write the start date in docs/decisions.md. Rule: after 14 days of the morning brief, if fewer than about a third of actions are acted on, shrink or change the system.

## B. Needs his decision
- [ ] First commit and push to https://github.com/dakshsawhneyy/second-brain.git (git is initialised on `main`, remote set, nothing staged). Show the file list and message first; `.env`, `raw/`, `index/`, `.venv/` are gitignored.
- [ ] Plan A vs Plan B for the models (after step 4).
- [ ] Whether the daily job may push to the repo automatically (default: always manual).

## C. Can be done offline
- [x] DONE 2026-11-17: next plan written: docs/superpowers/plans/2026-11-17-second-brain-stage-3-5.md (16 tasks; he must review it and choose the execution approach). Stages 3-5 = weekly review, lifecycle (tombstone demotion, consolidation into themes and the profile),
      resurfacing, book/experiment/friction workflows, publishable feed for his X/LinkedIn tools, AI-chat ingestion (his side only), evaluation set, cognee only if retrieval fails.
- [ ] Fix the deferred minors listed in docs/ledger.md (URL in actions, context.py break->continue, --limit vs failures, state-write failure resend,
      corrupt zero-length card, malformed Takeout entries, search --k cap, negative --n) if he wants them.

## Already done (do not redo)
Design + plan approved; all Stage 0b-2 code with TDD; independent security review and fixes; `.venv`; `.env` with token and owner id (gitignored);
goals/profile files; real embedding model downloaded; Ollama installed (no model yet); autostart task SecondBrainBot registered; git init + origin.

## Plan for Stages 3-5
Written: docs/superpowers/plans/2026-11-17-second-brain-stage-3-5.md. Build order: Tasks 1-12 can start on fixtures any time; Tasks 13-15 need the first real ingest and his sample chat exports. Awaiting his review and choice of execution approach (recommend Native, with an independent review of Task 12 feed and Tasks 13-14 chat privacy).
