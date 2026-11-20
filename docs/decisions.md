# Second Brain: locked decisions

Status: draft decisions, not yet the full design. Last updated 2026-11-17.

## Purpose
A personal growth system for one user. Goal: turn what the user consumes and thinks into
context that AI can use, nudge the user from consuming to producing, and feed an
automated build-in-public pipeline (X and LinkedIn). Not a product for others (to confirm).

## Core loop
Capture -> Distil -> Nudge -> Act -> Record result -> back into memory.
The Telegram bot completes the loop.

## Locked decisions
1. **Lifecycle, not deletion.** Irrelevant cards are demoted to tombstones (title, URL, date,
   topic, score) after 2-4 weeks with no review needed. Never fully deleted, because
   relevance changes with goals, drift stats need them, and re-imports must not be re-processed.
   Deleted: raw transcripts (after extraction, ~30 days) and anything the user flags as
   junk or sensitive. Weekly report shows a count, the top 3 surprises and a one-tap rescue.
2. **Tiers:** hot, warm, cold (tombstone), deleted. Unused cards decay; acted-on cards gain importance.
   Cards consolidate into weekly themes, then monthly themes, then the profile.
3. **Fixed-size context for AI:** short profile (about 1-2k tokens) plus top few retrieved cards.
   Prompt size does not grow with data size.
4. **One card schema for all sources:** source, type (consumed / thought / decided / acted /
   produced), timestamp, topics, key_points, importance, confidence, visibility
   (private / publishable), provenance pointer. New sources are adapters only.
5. **Store only the user's side of AI chats.** AI replies are kept only if the user agreed or acted.
6. **Three layers:** raw (local only, never on GitHub) -> cards (source of truth, private repo)
   -> distilled (themes, profile). cognee is a rebuildable index, deferred until plain
   JSON + search measurably fails.
7. **Runs on the user's laptop, no server.** Trigger: when the laptop is opened, the pipeline
   processes, then sends Telegram notifications. Must be idempotent and safe to re-run.
   The private repo is also the backup.
8. **Git rule:** no `git add`, `commit` or `push` without explicit approval each time
   (global instruction). Daily auto-push only if the user grants it as a standing exception.
9. **Privacy wall:** private vs publishable stores. The post generator reads publishable only.
   Telegram is not end-to-end encrypted for bots, so briefs stay non-sensitive.
10. **Posting is out of scope for this project.** The user is building separate X and LinkedIn
    draft tools that consume this data. This project's job is to make the data excellent and
    expose it through a stable read-only interface (see "Consumers"). Quality of the memory is the priority.
11. **Self-monitoring metrics** in the weekly review: act rate, skip rate, produced-to-consumed
    ratio, share of consumption linked to a goal, adapter health, weekly cost.
12. **Stop rule:** after 14 days of the morning brief, if fewer than about a third of items
    are acted on, shrink or change the system.
13. **Pilot before automation:** export YouTube history via Takeout, paste a week into Claude,
    check whether the weekly review is useful by hand.

14. **Zero cost.** Everything must be free. No paid APIs. Posting to X/LinkedIn is draft-and-copy
    (user posts manually), because the X API is pay-per-use. Free-tier cloud LLMs only see
    low-sensitivity data; private thoughts go to a local model only.
15. **Hardware (checked 2026-11-17):** i5-13500HX, 16 GB RAM, RTX 4050 laptop GPU (6 GB VRAM),
    196 GB free, Python 3.12, no Ollama yet. Fits 3-8B quantised local models.

16. **Read-only toward the user's other apps (hard rule).** The second brain only tracks and
    records. It never modifies, interferes with or depends on SkipATS (C:\Studies\Claude Code\startup_finder)
    or any other app of the user. If it needs a model or tool SkipATS also uses, it keeps its own
    copy. Reading SkipATS output is allowed only if the user grants it, and only as read-only input.

## Sources (user, 2026-11-17)
- Stage 1: YouTube, one account only (Takeout JSON first, yt-dlp later).
- Physical books: no file to import, so capture is manual and must be near zero friction:
  message the bot "book: <title> - <idea> - <action>", plus an evening nudge "what did you read?".
  Later option: photograph a highlighted page and read it locally with free OCR.
- AI chats (ChatGPT, Claude, Gemini): future version, user side only (decision 5).
- X and LinkedIn: cannot be scraped (and should not be). Reading is captured by sharing a link
  or note to the bot. The user's own posts can come in through each platform's official data export
  (free) as `produced` cards and voice samples for the downstream draft tools.

## Permissions (user, 2026-11-17)
Allowed: read anything and make copies of anything. Not allowed: change anything belonging to another app.

## Consumers (downstream tools the user will build separately)
The second brain is the data layer. Consumers: X draft tool, LinkedIn draft tool, other future tools, any AI.
Contract:
- Versioned card schema, documented, stable.
- Every card has provenance (where it came from), timestamp, confidence, visibility
  (private / publishable), and a source link.
- Read-only interface for consumers (local files in the repo first; CLI/MCP/HTTP later).
  Consumers never write into memory directly. A feedback channel (e.g. post performance) can
  come later through a defined entry point.
- A "publishable feed": only cards marked publishable, with the evidence behind each claim,
  so downstream drafts are fact-checkable.
- Also provides: current profile, current goals, recent themes, and style/voice samples if the user provides them.

## Schedule implications (user's routine, 2026-11-17)
- Laptop is on about 10am-11pm daily, so a lightweight local bot process can run all day
  (long polling), not only a run-on-open job. Quick capture and replies work in real time.
- Morning brief fires on first unlock or login. Evening check-in around 9-10pm: "what did you produce today?"
- Lots of unstructured time, so the brief should set one produce action early in the day.

## Future feature: opportunity finder (user request, 2026-11-17)
User has no product idea yet. Later, the system proposes SaaS ideas from his skills, learning
and friction, ranked by evidence of willingness to pay, not by how clever the idea sounds.
Inputs: skills and interests from memory, a "friction" log (things that annoyed him, questions
students keep asking), plus free external signals (Reddit, Hacker News, GitHub issues, startup
job posts via SkipATS). Output: ideas become `experiment` cards (hypothesis, cheapest test,
result, decision). Validation (conversations, landing page, pre-sell) is the bottleneck, not ideas.

## Risks to test early
- Chrome cookie access on Windows for yt-dlp (may need Firefox, Takeout or browser automation).
- youtube-transcript-api reliability and transcript availability.
- cognee extraction quality on personal data (only when we get to it).

## Open
- Personal tool only, or eventually offered to others (affects multi-user and hosting).
- User goals (interview in progress): they drive relevance scoring.

## 14-day stop-rule clock (started 2026-11-19)
- Day 1: 2026-11-19. Day 14: 2026-12-03. Decision day: 2026-12-03.
- Rule: after 14 days of the morning brief, if fewer than about a third of the brief's actions are acted on, shrink or change the system.
- Counted from: the bot's "did you use this?" buttons and his own check-ins. Started with thin data (a few session cards, no YouTube yet), so the first days measure the loop, not the content.
- Decided by Daksh on 2026-11-19. Mentor MVP runs in shadow mode during this window (docs/mentor-spec.md section 9).

## Work topics added (2026-11-19)
Added work/software-building, work/content-creation, work/admin-setup to the taxonomy because the local model mislabelled session cards (no fitting topic). Old session cards keep their old labels; the brief picks by project so it is unaffected.

## Advice via Claude (2026-11-19)
/ask sends Claude a bounded, redacted context pack (goals, last 3 advice exchanges, recent and keyword-matched journal/chat cards). private: entries never leave. Daily cap 10. Headless call measured at about 5 s for a short answer. Exchanges are saved as cards (source advice, id adv_<message id>); a failed call keeps the question as adq_<id>.

## Hardening pass (2026-11-19, bugs 1-10)
- cards/archive/profile/backups gitignored. Brief: a decision is not "Done". Brief numbering persisted in bot_state.json (last_ids).
- /ask pack: no claude-code session cards; uses Index.search (meaning + keywords) with keyword fallback; local-only cards never included.
- Index.update(): incremental (sig per card). `sb index`; runs inside `sb sync` every 2 h.
- Backup: `sb backup` / `sb restore`, Fernet+scrypt, needs SB_BACKUP_PASSPHRASE (+ SB_BACKUP_DIR); never plaintext. Daily inside `sb sync`.
- Alerts to Telegram: sync failed, no sync for 12 h, backup not set up (weekly) or failed.
- Bot: concurrent_updates on. Morning brief window 06:00-21:00 (late start still gets it).
- Brief: duplicate leftovers collapsed; leftovers a LATER card says were done are hidden (stem overlap >= 0.6).
- Still open: living profile (weekly Claude rewrite), mentor design pass, importers unverified on real exports.

## Mentor research and v2.1 design (2026-11-20)
157 people + science + comfort-zone cases researched (docs/research/). Design rewritten: docs/mentor-design-v2.md. Key overrides: no doubled/escalated penalties, no invented anecdotes, harsh = firm about behaviour and his own agreed rules, stop-pushing protocol, human reviewer.

## Mentor M0-M3 built (2026-11-20)
src/secondbrain/mentor/{persona,guards,ledger,state,onboarding,runner,flow}.py. Vikram on by default (SB_MENTOR=off to disable). Onboarding starts at the next 08:00-22:00 tick. Telemetry: every Claude/Ollama call logged to raw/usage.jsonl with section label and real tokens (claude -p --output-format json); `sb usage --days N` or /usage. Sections: mentor.onboarding/morning/evening/closeout/profile/parse/classify, ask, classify, sync.sessions/chats/index, ingest. Truth-over-comfort rule is in the persona prompt and tested.

## Data repo with auto-push (2026-11-20, approved by Daksh)
- Separate PRIVATE repo `dakshsawhneyy/second-brain-data`, cloned at `C:\Studies\Claude Code\second-brain-data` (`SB_DATA_REPO` in .env). The code repo still never holds data.
- `sb sync` (every 2 h) mirrors cards/, archive/, profile/ as plain text, then commits and pushes if anything changed (src/secondbrain/datasync.py). Failed push keeps the commit and retries next run; Telegram alert `data_failed` at most once a day.
- UPDATED 2026-11-20 (Daksh): `local-only` (/private) cards ARE copied to the data repo too (his own private repo). They are still never put in any Claude context pack (/ask, weekly review).
- Auto-push approval covers ONLY this data repo. Pushes of the code repo stay manual: ask each time. No `git add/commit/push` in the code repo without approval.
- Encrypted `sb backup` is optional now; with SB_DATA_REPO set, the "backup not set up" nag is off.
- Restore: clone the data repo and copy cards/, archive/, profile/ back into the project root.

## Voice notes (2026-11-20, Daksh)
- Voice/audio messages are transcribed LOCALLY (faster-whisper `small`, int8 CPU, model in raw/models/whisper; `scripts/fetch-whisper.py` downloads it with retries). Audio never leaves the PC; the transcript is then handled exactly like typed text.
- Rule: a voice note sent as a REPLY to the mentor's latest message answers him; a voice note on its own is a normal note (strict mode, voice only). Typed plain messages keep the old rule (a plain message while the mentor waits counts as his answer).
- Bot echoes "Heard: ..." so transcription mistakes are visible. Limit 20 min per note. Env: SB_VOICE=off, SB_WHISPER_MODEL (small|medium), SB_WHISPER_LANG (e.g. en).
- av is pinned <16: faster-whisper 1.2.1 breaks with av 19.

## Never lose a message (2026-11-20, Daksh)
- Durable inbox (src/secondbrain/inbox.py, raw/inbox.json): every owner text/voice/capture-command is written to disk first (handler group -1), removed only after the card is saved. Leftovers are retried every 60 s by the scheduler (after 90 s, max 30 tries, then one polite notice; the entry is kept).
- Voice notes that fail (offline, model error) are kept by Telegram file_id and re-transcribed later; recovered notes keep the ORIGINAL send time. Replays are idempotent (card id tg_<message_id>).
- Laptop off: Telegram holds undelivered messages for 24 h and delivers them when the bot starts. Messages older than 24 h at start-up are gone (Telegram limit). Workaround: forward them again or export the chat from Telegram Desktop.

## Undeliverable replies are queued (2026-11-20)
- Incident: a journal paragraph was saved (mo_32) and Vikram's reply was generated by Claude, but sending it failed (NetworkError) and the reply was lost; the leftover inbox entry would have been replayed as a duplicate note.
- Fix: outbox (src/secondbrain/outbox.py, raw/outbox.json). Mentor replies and /ask answers go through `_reply_or_queue`; failed sends are kept and re-sent in order every 60 s. A message the mentor handled is removed from the inbox as soon as the handler returns. Replay also skips messages that already have an `mo_<id>` card.

## /thought replaces /skip; bare commands open a reply box (2026-11-20)
- /skip command removed (the Skip button under each brief item stays). /thought <text> stores a thought with NO reply (a thumbs-up reaction only) and no related-notes lookup; it also works while the mentor is waiting.
- Telegram bots cannot pre-fill the input box from the command menu (tapping a command always sends it). So a bare /thought /book /todo /private /done /ask answers with a ForceReply prompt + placeholder; the next message he sends in that box is treated as that command's text (typed or voice). /ask prompt replies are never replayed after a crash.

## Root cause of the "bot does not reply" problem: broken IPv6 route (2026-11-20)
- Measured: curl to api.telegram.org over IPv6 failed 7 of 15; IPv4 15 of 15. With httpx and a new connection each time: default 2/30 ConnectError, IPv4-forced 0/30. DNS lists the IPv6 address first, so the bot kept hitting the bad route (ConnectError / TimedOut / failed sends).
- Fix: src/secondbrain/netfix.py `prefer_ipv4()`, called when the bot starts (process-wide getaddrinfo filter; falls back to all addresses if a host has no IPv4). The outbox (queued replies) remains the safety net for real outages.
- sb-status.ps1 now also shows inbox/outbox counts (should normally be 0).

## Mentor overwrote profile/profile.md; fixed (2026-11-20)
- When onboarding finished (14:01) the mentor wrote its generated profile over his hand-written profile/profile.md. Recovered from the data-repo history (commit a0b7e28). Now: profile.md = his hand-written file (never written by code), profile/onboarding.md = generated interview profile; `Mentor._profile_text` reads both. Test added.
- Next build: docs/superpowers/plans/2026-11-20-retrieval-and-memory-v2.md (Phase A = Tasks 1-3 first).

## Retrieval and memory v2, Phases A and B (2026-11-20, Daksh approved Tasks 1-4)
- Index v2: one search unit per paragraph (chunk), float32/float16 matrix cache, incremental scan, instant indexing of every saved note, WAL + staging-table swap so the bot and the sync can share the file. Measured: warm query 166 ms at 200k chunks.
- Real bug found and fixed: the /ask pack was cut off at the END, so the matched notes (the last section) never reached Claude. Sections now have their own budgets (total 9000). Profile reaches Claude up to 2500 chars (was 1800).
- Interview Q/A cards are chunked as the ANSWER with the question as search context (the bot no longer quotes its own questions back). "You wrote something close to this before": only earlier days, his own sources, cosine >= 0.72, never when he is replying, date + text once.
- Digests (day, week, month) and the living profile are built by the LOCAL model only, from notes that may reach a pack (not local-only, not session summaries, not ledger cards, not Claude's advice), only for COMPLETED days/weeks/months, only when the source set changed, at most 6 model calls per sync. `sb digest [--profile]`. Digest cards are source "digest" cards (searchable evidence, not "recent entries").
- The living profile (profile/living.md) is NOT written yet: it starts only after a completed week digest exists. The mentor reads living.md once it exists, else his hand-written profile.md plus onboarding.md. Open decision: local model (free; the first preview misfiled some points) or one Claude call a week.
- Eval: `sb eval` / `sb eval --suggest N` (profile/evals/questions.json is in the data repo, never the code repo). Honest result: on 38 short notes old and new retrieval are equal within noise; the gain is that the answering PARAGRAPH reaches Claude (13/16 vs 0/16 on long journals). See docs/experiments/retrieval-v2.md.

## Shared documents (2026-11-20, Daksh approved)
- He can send .txt, .md, .pdf and WhatsApp chats (.txt or .zip) to the bot. Images are NOT supported yet (asked for later). Files up to 20 MB; zips are read in memory (never extracted), max 40 MB unpacked, text files only, no nested zips; PDFs max 300 pages, text layer only (no OCR).
- The bot asks "what is this, and which one is you?" (ForceReply); his reply (typed or voice) is the description. A caption on the file skips the question. The LOCAL model reads his description (title, who he is in the chat, others' roles) and writes an approximate gist; the real text is stored in attributed chunks and searched like any note. Pending files live in raw/pending_docs/ until he answers; the file message is in the durable inbox until it has been read.
- Stored as source "document" cards (a parent + "part" cards). They are NEVER treated as his own words: excluded from his evidence, recent entries, digests, related-note suggestions, the living profile and eval questions. In an /ask pack they appear in their own section "MATERIAL HE SHARED (written by other people, NOT by him)" with its own budget (1500 chars), and the mentor is told to attribute it to its author.
- PRIVACY DECISION (Daksh, 2026-11-20): Claude MAY see excerpts of shared documents (they reach /ask packs). Per file he can keep one away from Claude by using the word "private" in his description or caption: every card is then local-only. NOTE: shared documents are mirrored to the private data repo like all cards, including other people's chat text.
- CLAUDE.md still lists only two approved private-data paths; it should be updated to add this third one when Daksh says so.

## Shared documents: independent review and fixes (2026-11-20)
A read-only reviewer found 4 Critical and 5 Important problems; all were fixed test-first (tests/test_doc_review_fixes.py, 37 tests):
- C1 two quick replies could race and "private" could lose -> one lock per document; a reply that arrives after saving and asks for privacy turns every card local-only (and re-indexes); private is sticky on re-import.
- C2 a reply to a file question was replayed after a crash as a PLAIN note Claude could see -> recorded as a document reply (typed or spoken), replayed into the document, never a note.
- C3 the private-key rule of the secret scrubber was quadratic and, because a regex holds Python's global lock, froze the WHOLE BOT (39 s at 0.56 MB). Now a linear scan with a bounded END search; text is cut to the size cap before scrubbing.
- C4 hostile PDFs/zips escaped error handling -> every parser failure becomes a clear message; a 90 s read timeout; pypdf >= 6.
- I1 orphaned files (question never sent / save failed after a caption) -> the inbox entry stays until the question is out; a failed save leaves a question to answer.
- I2 the private confirmation said "stays on this computer" -> now says Claude never sees it and that it is still copied to the private data repo.
- I3 a saved file can still be made private; I4 shared text is "data, not instructions" for Claude and figures from it may only be quoted with attribution; I5 "private" also recognises privately, confidential, sensitive, secret, "don't show/send Claude", "hide from Claude", "not for Claude".
Deferred minors: parse_whatsapp runs on the event loop (about 100 ms at the size cap); a download that keeps failing repeats its notice; WhatsApp dotted/ISO dates, system lines with a colon and iOS <attached:> lines are not specially handled; up to 3 local-model calls per document (the JSON helper retries once); saved-document records in raw/pending_docs.json are never pruned; day-first is assumed when every date is ambiguous.

## Context fixes from the real conversation (2026-11-20, Daksh: "the bot lacks proper context")
Reconstructing what Claude was actually sent at 21:02 for "/ask hope that makes sense now for your previous message" showed four faults:
1. Conversation memory: room for ~1000 chars, each exchange cut to 500, and when full the NEWEST exchange was dropped (the one "your previous message" means). Now THE CONVERSATION SO FAR holds the last 4 exchanges (question up to 700, answer up to 900 chars, budget 4000); the OLDEST drop first; the header says the last exchange is what "previous message" means.
2. Long messages were cut to 260 chars (pasted LinkedIn chats are ~4000 chars each). The newest 3 entries of the last 12 hours now keep up to 1000 chars; a pasted conversation is labelled "pasted conversation, not his own words" (looks_like_pasted_chat).
3. A vague follow-up searched its own empty words. Now, for a short or referring question, extra queries are built from the last exchange (its question, the start of its answer) and the newest note, and fused with the question's own results (retrieve(extra_queries=...)). Clear standalone questions get no extra queries.
4. WhatsApp speakers were SWAPPED: a small local model decided the other person was him, so Yeshwant's lines were stored as "Daksh:". Identity is now decided by rules before the model: the author called "You", or whose name is in SB_OWNER_NAMES (default "Daksh"), is him and the model cannot override it; if nobody is identifiable the labels stay neutral and no one is claimed as him; nobody who is "him" gets a role. The gist is built from the messages, not the WhatsApp banner. The extracted text of a saved document is now KEPT in raw/pending_docs/ (local only, never mirrored) so a wrong reading can be redone.
Also: documents shared in the last 48 hours are always introduced in MATERIAL HE SHARED (their description and who-is-who), whatever the question; its budget is 2200 chars with up to 6 passages. Pack cap 17000 chars (about 3.7k tokens typical; it was 11000).
Real data repaired (backup in the temp folder doc90_backup): doc_90 / doc_90_p1 re-labelled (Yeshwant ITFocus (Founder) / Daksh) and the gist rewritten.
