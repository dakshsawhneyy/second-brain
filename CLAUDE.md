# Second Brain project

Start every session by reading docs/NEXT_STEPS.md (what to do next), then docs/PROJECT_STATE.md, docs/design.md and docs/decisions.md.
Current plan: docs/superpowers/plans/2026-11-17-second-brain-stage-0b-2.md.

Hard rules (from the user):
- Everything must be free. No paid APIs.
- Read-only toward the user's other apps, especially SkipATS (C:\Studies\Claude Code\startup_finder). Copy if needed, never modify or depend on them.
- No git add/commit/push without the user's explicit approval each time.
- Private data (thoughts, books, goals) goes to a non-local model only in two user-approved ways (confirmed 2026-11-19): (1) the mentor's weekly review, /deep and miss-pattern analysis, with a TRIMMED summary; (2) the bot's `/ask` command, which sends Claude (headless `claude -p`, Sonnet 5.5) the question plus a bounded context pack built locally from his own journal/advice/chat cards and goals, secrets redacted. Entries saved with `private:` (card channel `local-only`) are NEVER put in any pack. Session summaries, triage and daily mentor messages stay on the local model. Every /ask exchange is saved back as a card (source `advice`).
- Never write the Telegram token or any secret into docs, code or memory. Secrets live only in .env (gitignored).
- Think and push back honestly; do not just agree. Give a recommendation first, then the reasoning.
