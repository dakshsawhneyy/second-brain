# Vision additions (2026-11-19, from Daksh)

Status: ideas and decisions recorded from the chat; not yet in design.md or a plan.

## Decisions
- No browser history in the brain (too noisy).
- Google Takeout is a one-time backfill (requested 2026-11-19 16:20, JSON, history only). It is manual, so it is not a daily source. Daily YouTube capture is still undecided.
- Keep the current Telegram bot token (accepted by Daksh).
- SkipATS: only a one-way read-only export may ever be used, and only after his explicit yes. No live link.

## Wanted features
1. Context for any AI (Claude, GPT): context pack now; local MCP server for Claude after the first ingest works; ChatGPT via paste-in or custom-instructions file.
2. Mentor check-in bot on Telegram: daily questions (what did you ship, learn, what blocks you), answers saved as cards, blunt weekly review. Persona: direct mentor, focus on shipping, no flattery, no pretending to be a billionaire.
3. Claude Code session summaries stored in the brain (session-end hook).
4. Application tracker and interview prep from cards (needs the SkipATS read-only export).
5. Idea log with evidence, experiment log, customer-pain notes.
6. Lifecycle for growing data: reuse design 5b (hot/warm/cold tombstones, delete only raw transcripts and flagged junk).

## Later the same day (2026-11-19)
- SkipATS is Daksh's own automated job-hunt tool (bet 1). He does NOT plan to make it public. Only the thin read-only slice (git log subjects, weekly funnel numbers) may feed the brain; no logs, no hr_list.csv, no secrets, no db.dump for now.
- He proposed letting Claude Sonnet 5.5 handle mentor analysis and answers instead of the local 7B. Recommended hybrid, awaiting his confirmation of scope: local 7B for frequent short messages; Claude (Sonnet 5.5) for the weekly review, a /deep command and miss-pattern analysis, receiving a TRIMMED summary only (commitments, evidence results, card ids; no raw feelings, health or money details).
- Cost of headless `claude -p` is unverified (subscription limits vs separate credit pool). Do not rely on it until Task 6 measures it. The hard rule "everything free" still applies.
- CLAUDE.md still says private data never goes to a non-local model. It is NOT changed until Daksh confirms the exact scope above.
- Mentor spec (Opus 5.5 review) recommends: do not build before ingest, bot check and the 14-day clock; ship the MVP in shadow mode first; delay penalties to week 3 or later. Daksh agreed.

## Privacy rule that applies to all of it
Private data never goes to a non-local model. Mentor chat uses the local model. Deep advice goes through a Claude session that Daksh starts himself with a context pack.

## Built 2026-11-19 (300 tests pass)
- `sb sessions`: summarises Claude Code transcripts (~/.claude/projects, all projects except temp) into private `cc_<session>` cards with the LOCAL model only (no Claude quota). Secrets redacted before the model sees anything; active sessions (<10 min) skipped; unchanged sessions skipped.
- `sb chats`: same for a claude.ai data export dropped in raw/claude-chats/ (zip or conversations.json) -> `ch_<uuid>` cards. UNTESTED against a real export; parser written from the expected format.
- `sb sync` + scheduled task SecondBrainSync (every 2 hours, 3 summaries per source per run, log raw/sync.log). Remove with scripts/install-sync-task.ps1 -Remove.
- Known weakness: the 7B often picks a wrong topic (taxonomy has no content-creation topic). Fix later by adding a topic or a rule.
- Bot: the autostart task had never run; started by hand at 17:34 on 2026-11-19 after network resets; no `tg_` card seen yet from his test message.

## Recommended order
Takeout arrives -> ingest 100 -> spot-check -> bot and morning brief -> mentor check-in bot -> session summaries -> Claude MCP server -> SkipATS export -> public feed for his posting tool.
