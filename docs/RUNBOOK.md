# Runbook

All commands run from `C:\Studies\Claude Code\z second brain` with the project venv.

```
.\.venv\Scripts\python -m pytest                      # run the tests (slow tests excluded)
.\.venv\Scripts\python -m pytest -m slow              # includes the real embedding-model test (downloads a model)
.\.venv\Scripts\python -m secondbrain.cli ingest --takeout raw\takeout\watch-history.json --limit 100
.\.venv\Scripts\python -m secondbrain.cli search "kubernetes networking"
.\.venv\Scripts\python -m secondbrain.cli export-batch --takeout raw\takeout\watch-history.json --n 10
.\.venv\Scripts\python -m secondbrain.cli bot         # run the Telegram bot in the foreground
```

(`sb ...` works too if the venv's Scripts folder is on PATH.)

## First-time setup checklist
1. `.env` exists with SB_TELEGRAM_TOKEN and SB_OWNER_TELEGRAM_ID (done). Regenerate the token in BotFather (/revoke) because it was pasted in chat once.
2. Request the YouTube Takeout (JSON, history only) and put it at `raw\takeout\watch-history.json`.
3. Install Ollama and one 7-8B model, then set `SB_OLLAMA_MODEL` in `.env` (ask first; see Task 6 in the plan).
4. Run the Claude usage experiment (Task 6) and set `SB_ROUTE_*` accordingly.
5. `ingest --limit 100`, spot-check 20 cards, write the findings in `docs\experiments\stage1-spot-check.md`.
6. Autostart (needs approval): `powershell -ExecutionPolicy Bypass -File scripts\install-autostart.ps1` (remove with `-Remove`).
   Do not run the bot by hand while the task runs: Telegram allows one poller per bot.

## Where things live
- cards/ (source of truth, git), archive/tombstones.jsonl, profile/ (goals.md is read by the triage model; keep a `Focus:` line, it is shown in the morning brief), schemas/card.v1.json
- raw/ and index/ are local only (gitignored): transcripts, Takeout files, bot_state.json, bot.log, search index, downloaded models.
- Progress ledger and rulings: docs/ledger.md. Design: docs/design.md. Plan: docs/superpowers/plans/.

## Safety rules baked in
- Triage prompts contain your goals, so triage only runs on a local model (the router refuses otherwise).
- Extraction prompts carry no personal context and may use a free cloud model.
- The bot answers only the owner's private chat; logs never include the token.
- Cards default to private. Nothing is pushed to git without your approval.
