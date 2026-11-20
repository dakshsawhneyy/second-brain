# Second Brain: project state and recap

Last updated 2026-11-17 (end of build session 1). Read this first in any new session, then docs/design.md and docs/RUNBOOK.md.

## What we are building
A personal memory and growth system for Daksh (final-year CS, infra/DevOps/SRE, Jammu, born 23 Dec 2005).
It turns what he consumes (YouTube first, then physical books, AI chats, shared links) into scored, traceable JSON
memory cards, gives any AI his context, and pushes him from consuming to producing through a Telegram bot.
It is the DATA LAYER. His X and LinkedIn draft tools are separate products that will read from it.

## Why (his goals)
- Rs 20 lakh income in the next year; dream: first millionaire in his family; target 1 million USD by age 25 (Dec 2030).
  Any of total income, net worth or value of his own company counts. Track all three separately.
- Two bets: (1) remote infra role (DevOps/SRE/Platform) at a foreign startup, (2) sell his own product.
  Not teaching, not shorts/reels or X-posting as income. Fail fast, experiment, record the lessons.
- SkipATS (C:\Studies\Claude Code\startup_finder) is personal and proof-of-work. NEVER modify or depend on it.
- Free time is high (course finished, college only exams). Laptop is on about 10am-11pm. Claude Pro plan is shared with other platforms.

## Core idea
Loop: Capture -> Distil -> Nudge -> Act -> Record result -> back into memory. The Telegram bot closes the loop.
Mantra: the system must increase what he ships, or we shrink or kill it (14-day stop rule: act rate under about 1/3).

## Key design decisions (full list: docs/decisions.md, full design: docs/design.md)
- Cards (JSON, git) are the source of truth. Index (SQLite FTS5 + local embeddings) is rebuildable. cognee deferred until retrieval fails.
- Two axes: topic x format (docs/taxonomy.md). Entertainment = noise. Multi-topic content = one card, topic per key point, never copied.
- Score is deterministic code: (50*max(bet_job,bet_product)+20*actionability+15*novelty+15*quality+5)//10; keep at 40+; entertainment capped at 20.
- Lifecycle not deletion: hot/warm/cold tombstones; delete only raw transcripts (~30 days) and flagged junk. Fixed-size AI context (profile + top-k).
- Scaling stages S1/S2/S3 by card count with measured triggers; eight noise controls (design 5b).
- Privacy: visibility defaults private; triage prompts contain his goals so triage runs on a LOCAL model only (router enforces; a remote Ollama URL counts as non-local);
  extraction carries no personal context and may use a free cloud model; the bot answers only the owner's private chat.
- Model routing: local (Ollama) triage; free cloud tier (Gemini/Groq/NVIDIA) extraction of public transcripts; Claude weekly synthesis.
  Task 6 experiment measures real Claude Pro usage and compares quality, then picks Plan A (Claude direct) or Plan B (routing). Headless `claude -p`
  billing is reported inconsistently (separate credit pool since 15 Jun 2026?): do not depend on it unverified.
- Consumers contract: versioned schema, read-only, publishable feed with provenance. Posting is out of scope here.
- Hard rules: zero cost; read-only toward other apps; no git add/commit/push without his approval each time; no scraping X/LinkedIn.

## Status (build session 1, 2026-11-17)
- Interview, design, plan: done and approved. Plan: docs/superpowers/plans/2026-11-17-second-brain-stage-0b-2.md.
- IMPLEMENTED with TDD (245 tests passing, 1 slow test deselected): config, card schema + atomic store, Takeout adapter, transcripts (cache, backoff,
  RateLimited vs no-transcript), LLM providers + sensitivity router, triage + deterministic scoring, extraction, idempotent ingest pipeline,
  SQLite hybrid search index, fixed-budget context pack, Telegram capture parser, morning/evening brief builders, owner-only bot with asyncio scheduler,
  CLI (`sb ingest | search | bot | export-batch`), autostart script (written, NOT run), runbook, goals/profile files.
- Verified live: real transcript fetch works from the laptop; real bot token works through our app code (@second_brain_of_daksh_bot, no message sent).
- Progress ledger with every ruling: docs/ledger.md. Independent security review of the privacy gate / bot / failure modes was requested; see ledger for outcome.
- Not a git repo yet (waiting for his yes on `git init` + `git remote add origin https://github.com/dakshsawhneyy/second-brain.git`). No commits made.

## Pending (needs the user)
1. Takeout export of YouTube history (JSON) -> raw/takeout/watch-history.json.
2. Approval to install Ollama + one 7-8B model, then set SB_OLLAMA_MODEL in .env.
3. Task 6 experiment: measure Claude usage, compare quality, choose Plan A or B (set SB_ROUTE_* in .env).
4. Approval to download the embedding model (slow test) and to run `scripts/install-autostart.ps1`.
5. A clear yes/no on `git init` (every add/commit/push still needs approval each time).
6. Regenerate the Telegram bot token in BotFather (it was pasted in chat once) and update .env.
7. Acceptance: ingest 100 videos, spot-check 20 cards, start the 14-day stop-rule clock.
8. Next plan: weekly review, lifecycle (tombstone demotion, consolidation), resurfacing, books/experiments, publishable feed, AI chats, evaluation set.

## Update 2026-11-17 (after the review fixes)
- DONE: git init (branch main, origin = https://github.com/dakshsawhneyy/second-brain.git, NOTHING added/committed/pushed); real embedding model downloaded and slow test passed;
  autostart task SecondBrainBot registered and verified (script bug fixed: it hid a failure); Ollama 0.40.16 installed; independent review fixes applied (266 tests pass).
- BLOCKED BY NO INTERNET: the model pull failed at 1% (about 2 MB/s, connection aborted). Later run: & "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" pull qwen2.5:7b
  (resumable, about 4.7 GB; smaller fallback qwen2.5:3b), then set SB_OLLAMA_MODEL=qwen2.5:7b in .env.
- STILL NEEDED (all need internet unless noted): Takeout export request (start first, takes hours) -> raw/takeout/watch-history.json; model pull; regenerate bot token in BotFather;
  Task 6 Claude-usage experiment; 100-card ingest + 20-card spot-check; first live bot check; start the 14-day stop-rule clock.
- NEEDS HIS DECISION: first commit and push (each needs explicit approval); Plan A vs B after the experiment; whether to write the next plan (weekly review, lifecycle, resurfacing, books, publishable feed).

## Stage 3-5 plan
Written 2026-11-17: docs/superpowers/plans/2026-11-17-second-brain-stage-3-5.md (lifecycle, themes, weekly review, resurfacing, beliefs, publishable feed, AI chats, evaluation set). Not started; awaiting review.
