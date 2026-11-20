# Second Brain: design

Status: DRAFT for user approval. Nothing is built until this is approved.
Date: 2026-11-17. Companion docs: decisions.md (locked decisions), profile-draft.md, taxonomy.md.

## 1. Intent and why

Daksh is a final-year CS student (infra/DevOps/SRE skills, taught a 200+ hour multi-cloud course).
He wants Rs 20 lakh income over the next year and, long term, to be the first millionaire in his family.
Two bets: (1) a remote infra role at a foreign startup, (2) selling a product of his own.
His problem: he consumes a lot (YouTube, physical books, AI chats) and wants it to turn into
output and compounding growth. LLMs have no context about him, so their answers are generic.

The second brain is a personal memory and growth system that:
1. Captures what he consumes and thinks, filters noise, and keeps what serves his two bets.
2. Gives any AI his context (profile + relevant memory) so answers are personal.
3. Pushes him from consuming to producing, via a Telegram bot (morning brief, evening check-in, weekly review).
4. Provides clean, traceable, versioned data that his separate X and LinkedIn draft tools will read.

Success means: after 14 days he has acted on a meaningful share of the brief's actions, his
produced-to-consumed ratio goes up, and AI answers with his memory beat the same AI without it.

## 2. Goals, non-goals, anti-goals

Goals
- High-quality, traceable memory cards from YouTube (stage 1), then books, AI chats, links.
- Relevance scoring against his two bets and the taxonomy (docs/taxonomy.md).
- A Telegram bot that closes the loop (nudge, act, record the result).
- A stable read-only interface for downstream tools.
- Free, local, runs on his laptop.

Non-goals
- Posting to X or LinkedIn (separate tools he builds himself).
- Scraping X or LinkedIn.
- Multi-user, hosting, or selling this (personal tool; revisit later).
- Modifying SkipATS or any other app of his (read and copy only).
- A dashboard or web UI.

Anti-goals (would be a failure even if it technically works)
- A growing pile of summaries he never revisits (the collector's fallacy).
- A system that becomes productive procrastination instead of increasing what he ships.
- An AI that only flatters him.
- A bot he ignores after two weeks.
- Any private thought leaking into a public draft.

## 3. Constraints
- Zero cost: free tools only, no paid APIs.
- Laptop only, no server. Laptop is open about 10am-11pm. Python 3.12, i5-13500HX, 16 GB RAM, RTX 4050 6 GB.
- Free-tier cloud LLMs get only low-sensitivity data. Private data goes to a local model only.
- Read-only toward his other apps; may copy anything it needs.
- Git: no add/commit/push without his explicit approval each time.
- No scraping X or LinkedIn. YouTube access must degrade gracefully (Takeout is the stable path).

## 4. Approaches considered

A. Memory first, then content. Clean but slow to show value.
B. Content engine first. Quick visible value but shallow memory. (Now out of scope anyway.)
C. Thin vertical slice (chosen): one source (YouTube), cards, local search, Telegram brief and
   replies, then widen. Tests the riskiest parts early (YouTube access, extraction quality, whether he uses the brief).

Memory layer choice: plain JSON cards + SQLite + local embeddings first. cognee (Apache-2.0, local)
is deferred until retrieval measurably fails, because at a few hundred to a few thousand cards a
graph database is overkill. Cards stay the source of truth, so adding cognee later means indexing, not migrating.

## 5. Architecture

```
Sources -> adapters -> raw (local) -> triage -> extract -> cards (git) -> index (local, rebuildable)
                                                         -> lifecycle (hot/warm/cold)
                                                         -> consolidation (themes, profile)
Telegram bot <- brief/review generators <- retrieval over cards + profile
Consumers (his X/LinkedIn tools, any AI) <- read-only interface <- publishable feed
```

Repo layout (private repo; raw/ and index/ are gitignored)
```
cards/YYYY/MM/<id>.json      hot and warm cards
archive/tombstones.jsonl     cold, one line per card
themes/weekly/, themes/monthly/
profile/profile.md, profile/goals.md
feed/publishable.jsonl
schemas/card.v1.json
raw/        (local only: transcripts, takeout files; deleted after ~30 days)
index/      (local only: SQLite + embeddings; rebuildable)
```

Pipeline (idempotent; safe to re-run; deduplicates by source + source id)
1. Ingest: read new items from an adapter (stage 1: Takeout watch-history JSON; later yt-dlp).
2. Fetch transcript: youtube-transcript-api, fall back to local faster-whisper, else mark "no transcript".
3. Triage (local model, cheap): topic, format, relevance sub-scores, entertainment vs growth. Below threshold: write tombstone and stop.
4. Extract (only items above threshold): key points, each with its own topic, an action suggestion, confidence.
5. Write card JSON, update the index.
6. Lifecycle job (weekly): demote, decay, consolidate.

Relevance score (my call; tune after the pilot): code combines LLM sub-scores 0-10:
bet_alignment 50%, actionability 20%, novelty 15%, quality 15%. Combination is deterministic code, not the LLM,
so scores are comparable over time. Entertainment topic caps the score low.

Card schema v1 (example)
```json
{
  "schema": "card.v1",
  "id": "yt_<videoId>",
  "source": "youtube",
  "type": "consumed",
  "title": "...", "url": "...", "channel": "...",
  "consumed_at": "2026-11-17T10:42:00+05:30",
  "topic": {"primary": "infra/sre", "secondary": ["ai/agents"]},
  "format": "podcast",
  "relevance": {"bet_job": 7, "bet_product": 3, "actionability": 6, "novelty": 5, "quality": 7, "score": 62},
  "key_points": [{"text": "...", "topic": "startups/pricing", "t": "00:41:10", "confidence": 0.8}],
  "action": {"text": "Try X", "status": "open"},
  "visibility": "private",
  "tier": "hot",
  "provenance": {"transcript": "captions|whisper|none", "model": "local-7b", "processed_at": "..."},
  "user": {"rating": null, "acted": null}
}
```
Types: consumed, thought, decided, acted, produced, experiment, friction, book.
Tombstone = id, source, title, url, date, topic, score (one line).

Lifecycle
- Hot: recent or acted-on or highly rated. Warm: older but still relevant. Cold: tombstone, auto after 2-4 weeks of low relevance, no review needed.
- Weekly report shows a count and top 3 surprises with one-tap rescue.
- Unused cards decay; acted-on or resurfaced-and-used cards gain importance.
- Deleted: raw transcripts after ~30 days, and anything he flags junk or sensitive.
- Consolidation: weekly theme -> monthly theme -> profile. Originals go cold.

Context for AI (fixed size): profile (~1-2k tokens) + top-k retrieved cards. Never grows with data size.

## 5b. Scaling plan (data will grow; noise must not)

Size math: a card is about 1-2 KB. 10k cards is about 20 MB, 100k is about 200 MB. Storage is never
the problem. The real risks are noisy retrieval, slow pipelines and rising LLM usage, so scaling
is about keeping retrieval and processing cost flat as data grows.

| Stage | Cards | Storage and search | Memory structure | Move up when (measured) |
|---|---|---|---|---|
| S1 | under 1k (first ~6 months) | JSON files + SQLite, brute-force local embedding search | profile + top-k, weekly themes | latency over 2 s, or eval score drops |
| S2 | 1k-10k | SQLite FTS5 (keyword) + vector index, hybrid search, rerank by importance and recency | hot/warm/cold tiers, monthly themes | multi-hop questions fail ("how do my startup notes connect to my SRE notes") |
| S3 | 10k-100k, many sources (AI chats, books) | per-month sharding, compressed tombstone archive, quantised embeddings; add cognee graph for entities and relations | daily -> weekly -> monthly -> quarterly -> yearly consolidation; profile rewritten from themes, not raw cards | weekly pipeline run over 30 minutes, or repo over 500 MB |

Noise control at every stage:
1. Gate at ingestion: triage threshold adapts to his ratings and skips (what he skips raises the bar for similar items).
2. Dedupe: exact by source id; near-duplicates by embedding similarity (about 0.92+) in the same topic are merged, keeping the best card.
3. Source quotas: a high-volume source cannot dominate retrieval (cap per source in the top-k).
4. Decay: unused cards lose importance; tombstone when low.
5. Consolidation: old cards fold into themes; the theme answers broad questions, the card answers precise ones.
6. Fixed retrieval budget: profile + top-k, regardless of total size.
7. Regression test: a fixed question set (about 15, grown over time) run weekly; a score drop means retrieval or noise got worse.
8. Weekly health numbers: cards by tier, noise share, retrieval score, run time, LLM usage.

## 5c. Model routing (Claude Pro is shared with his other platforms)

Facts (checked 2026-11-17): Pro has a five-hour limit and a weekly limit shared across Claude and
Claude Code; no token numbers are published. Whether unattended `claude -p` runs draw from the
subscription or a separate metered credit pool is reported inconsistently (a June 2026 change is
described in third-party sources, not confirmed on Anthropic's support page). So the scheduled
pipeline must not depend on `claude -p`.

Routing (quality where it matters, no daily drain on the shared Claude quota):
| Task | Volume | Model |
|---|---|---|
| Triage (topic, format, relevance) | high | local model via Ollama (free, private, unlimited) |
| Extraction of YouTube keepers | medium | free cloud tier (Gemini / Groq / NVIDIA, which he already evaluated in SkipATS) because YouTube transcripts are public content; fall back to local |
| Private material (own thoughts, books, goals) | low | local model only |
| Weekly review, profile update, belief audit | low, highest value | Claude in an interactive session he starts (about once a week), reading cards from the repo |

Cost controls: cache by source id (never reprocess), batch several items per call, strip sponsor
and filler segments before sending, cap daily calls per provider, provider abstraction so the
routing table can change without touching the pipeline.

## 6. Telegram bot (runs while the laptop is open)

- Morning brief (first unlock): goal reminder, yesterday's learning in 2-3 lines, ONE produce action before any consuming. Buttons: Done / Later / Skip.
- Evening check-in (~9-10pm): "What did you produce today? What did you read?" Free text becomes cards.
- Quick capture: any message becomes a card. Prefixes: `book:`, `idea:`, `friction:`, `experiment:`, `decided:`; shared links become link cards.
- Weekly review (weekend): themes, consumed vs produced, say-do gap, goal-linked share of consumption, entertainment hours, top 3 demoted surprises, contradictions, adapter health, cost.
- Resurfacing: one old insight a day with "did you use this?".
- Ignoring is data: skipped items lower relevance; high skip rate makes the bot send fewer, better messages.
- Challenge mode: on request, argues against a stored belief.
- Briefs stay non-sensitive (Telegram bots are not end-to-end encrypted).

## 7. Consumers contract (for his X and LinkedIn tools)
- Versioned schema in schemas/. Breaking changes bump the version.
- Read-only: consumers read feed/publishable.jsonl, profile, goals, themes. They never write to memory.
- Every claim traces to a card with provenance, timestamp, confidence.
- Only visibility=publishable cards appear in the feed. Default is private. Publishable requires an explicit mark by him.
- Style samples: his own posts via official platform data exports, stored as `produced` cards.
- Later: a defined feedback entry point (e.g. post performance) back into memory.

## 8. Stages and exit criteria

Stage 0, pilot (before any automation): export YouTube history via Takeout, run a week through Claude by hand.
Exit: he finds the weekly summary useful. If not, rethink before building.
Stage 0b, Claude usage experiment (decided with the user 2026-11-17: measure, do not guess):
- Plan A: use Claude directly for extraction and the weekly review. Plan B: the routing table in 5c (saved, ready).
- Protocol: in a fresh session, note the usage readings first (five-hour and weekly, from his account
  usage page or /usage). Process a fixed batch (about 10 videos of mixed length) through Claude for
  extraction. Read usage again. Compute percent of the five-hour window per video and per day at his
  real volume. Repeat once with a small headless `claude -p` batch to see which pool it draws from
  (subscription limits or a separate credit pool), checking both.
- Also record quality: spot-check the extracted key points against the source, and compare with a
  local-model run of the same batch.
- Decision rule (my default; he can change it): keep Claude in the daily run only if the projected
  daily cost is about 10% of one five-hour window or less AND it does not make him hit limits on
  days he is building with his other platforms. Otherwise switch to Plan B. The provider is
  swappable, so the switch is a config change, not a rewrite.
Stage 1, ingest: Takeout JSON -> cards for YouTube, triage + extraction on a local model, local search.
Exit: 100 cards, spot-check accuracy on 20 (key points correct, topics right), cost is zero.
Stage 2, bot: morning brief, evening check-in, quick capture, buttons.
Exit: 14 days of use; act rate above about one third, else shrink or change (stop rule).
Stage 3, review and lifecycle: weekly report, tombstones, consolidation, resurfacing, metrics.
Stage 4, widen: books (manual), links, experiment and friction cards, profile auto-update with belief audit.
Stage 5, AI chats (his side only), yt-dlp automation, the evaluation set (about 15 questions with and without memory), cognee only if retrieval fails.
Later: opportunity finder (docs/decisions.md).

## 9. Risks and mitigations
- Chrome cookie access on Windows may block yt-dlp: use Takeout first, Firefox or other fallback later.
- Transcript availability and rate limits: Whisper fallback; slow, polite requests.
- Local 7B model quality: use it for triage; use free cloud models only for low-sensitivity heavier steps; spot-check accuracy in stage 1.
- Free-tier limits and policies change: provider abstraction so models are swappable.
- Wrong inferences: every profile belief links to evidence cards; weekly belief audit; he can edit or delete.
- Echo chamber: challenge mode, contradiction detection.
- Privacy: private repo, raw data never pushed, visibility default private, local model for private data.
- Laptop failure: private repo is the backup (pushes need his approval).
- Scope creep: this project is the memory and the bot only.

## 10. Marked as builder's calls (my defaults; he can change)
- Relevance weights and thresholds; tombstone timing (2-4 weeks); raw retention (30 days).
- SQLite + local embeddings for search; Ollama for the local model; python-telegram-bot.
- Windows Task Scheduler (or a login-started background process) to start the bot.
- Local embedding model: his own copy of bge-small (not shared with SkipATS).

## 11. Needed from him before building
- Approve this design (or tell me what to change).
- Request a Takeout export of YouTube watch history (JSON).
- Create a Telegram bot with BotFather and keep the token private.
- Allow installing Ollama and a small model (approval before installing anything).
- Decide whether daily pushes to the private repo are allowed automatically or always manual.
- Optional: what "millionaire" means in numbers and by when, so the profile has a concrete target.
