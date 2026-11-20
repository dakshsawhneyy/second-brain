# Second Brain, Stages 0b-2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn a YouTube Takeout watch history into scored, traceable JSON memory cards, searchable locally, with a Telegram bot that sends a morning brief and captures notes; and measure Claude usage to pick the model routing.

**Architecture:** A Python package `secondbrain` with small modules: adapter -> transcript -> triage -> extract -> card store (JSON files, source of truth) -> SQLite index (rebuildable) -> context pack and Telegram bot. All LLM calls go through a `Provider` abstraction with a sensitivity gate, so routing (local vs free cloud vs Claude) is configuration.

**Tech Stack:** Python 3.12, pydantic v2, httpx, sqlite3 (FTS5), fastembed (bge-small, own copy), youtube-transcript-api, python-telegram-bot (async, v21+), Ollama (local model), pytest.

**Spec:** `docs/design.md` (companions: `docs/decisions.md`, `docs/taxonomy.md`, `docs/profile-draft.md`). Project root: `C:\Studies\Claude Code\z second brain`.

## Global Constraints

- Python 3.12 (`C:\Program Files\Python312\python.exe`), Windows 11, runs only on the user's laptop; no server.
- Zero cost: free tools only, no paid APIs. Claude is used only after the Task 6 experiment says so.
- Read-only toward his other apps. Never import from, modify, or depend on `C:\Studies\Claude Code\startup_finder` (SkipATS). Keep our own model copies.
- Visibility defaults to `private`. Private-sensitivity data is never sent to a non-local provider.
- `raw/`, `index/`, `.env` are gitignored and never pushed. Cards are the source of truth; the index is rebuildable.
- No `git init`, `git add`, `git commit` or `git push` without the user's explicit approval each time. The project is not a git repo yet. Each task ends with a **Checkpoint** step that only asks him.
- No scraping X or LinkedIn. YouTube history comes from Google Takeout first.
- The Telegram bot answers only the owner's Telegram user id. The token is never logged.
- Taxonomy and topic ids are exactly those in Task 2 (from `docs/taxonomy.md`).
- Installing anything (pip packages, Ollama, models) needs the user's approval first.

## Review Focus

1. **Sensitivity leak:** a card or thought marked private reaching a cloud provider. Expected: `route()` raises `SensitivityError`; nothing is sent. (Task 5)
2. **Stranger messages the bot:** a non-owner Telegram user sends commands. Expected: ignored, no reply, no card written. (Task 14)
3. **LLM returns junk:** invalid JSON, unknown topic, score outside 0-10. Expected: one retry, then topic `uncertain` and the item skipped with a logged failure; never a garbage card. (Tasks 5, 7, 8)
4. **Crash or sleep mid-run:** half-written file, re-run after interruption. Expected: atomic writes, re-run creates no duplicates and repeats no LLM calls. (Tasks 2, 9)
5. **Messy inputs:** Takeout entries with no URL (removed videos), ads, community posts, emoji or non-English titles; transcripts disabled or rate-limited (429). Expected: skipped or flagged `transcript: none`, bounded retries, progress kept. (Tasks 3, 4, 9)

---

## File Structure

```
pyproject.toml, .gitignore, .env.example
src/secondbrain/
  config.py        paths and settings
  schema.py        Card, Tombstone, taxonomy constants, validate_topic
  store.py         atomic card and tombstone storage
  adapters/takeout.py   Takeout JSON -> WatchItem
  transcripts.py   fetch, cache, chunk transcripts
  llm.py           Provider protocol, Ollama and OpenAI-compatible providers, complete_json, route
  triage.py        sub-scores, deterministic score, keep or tombstone
  extract.py       key points and action from a transcript
  pipeline.py      idempotent run_ingest
  embed.py         Embedder protocol, FastEmbedder, HashEmbedder (tests)
  index.py         SQLite FTS5 + vectors, hybrid search
  context.py       fixed-budget context pack (profile + top-k)
  bot/capture.py   parse_capture
  bot/brief.py     morning brief and evening check-in builders
  bot/app.py       Telegram handlers, owner allowlist
  cli.py           `sb` commands
scripts/install-autostart.ps1
tests/ (one test file per module), tests/fixtures/
cards/, archive/, themes/, profile/, feed/, schemas/   (data folders)
raw/, index/    (gitignored, local only)
```

---

### Task 1: Project scaffold and config

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `.env.example`, `src/secondbrain/__init__.py`, `src/secondbrain/config.py`, `tests/test_config.py`
- Create folders: `cards/`, `archive/`, `themes/`, `profile/`, `feed/`, `schemas/`, `raw/`, `index/`

**Interfaces:**
- Produces: `Settings` dataclass (frozen): `root: Path`, `cards_dir`, `archive_dir`, `raw_dir`, `index_path`, `profile_path`, `goals_path`, `owner_telegram_id: int | None`, `telegram_token: str | None`; `load_settings(root: Path | None = None, env: Mapping[str, str] | None = None) -> Settings`.

- [ ] **Step 1: Ask the user to approve installing dependencies** (`pydantic`, `httpx`, `youtube-transcript-api`, `fastembed`, `python-telegram-bot`, `pytest`) into a project venv `.venv`. Wait for yes.
- [ ] **Step 2: Write failing tests** in `tests/test_config.py`: `test_load_settings_defaults_paths_under_root` (cards_dir == root/"cards", index_path == root/"index"/"brain.db"); `test_owner_id_parsed_from_env` (`env={"SB_OWNER_TELEGRAM_ID":"123"}` gives `owner_telegram_id == 123`); `test_missing_token_is_none`.
- [ ] **Step 3: Run** `.venv\Scripts\python -m pytest tests/test_config.py -v`. Expected: FAIL (module missing).
- [ ] **Step 4: Implement** `config.py`, `pyproject.toml` (package in `src/`, pytest config `pythonpath = ["src"]`), `.gitignore` (`raw/`, `index/`, `.env`, `.venv/`, `__pycache__/`), `.env.example` (`SB_OWNER_TELEGRAM_ID=`, `SB_TELEGRAM_TOKEN=`, `SB_OLLAMA_MODEL=`, cloud keys blank). Env names: `SB_OWNER_TELEGRAM_ID`, `SB_TELEGRAM_TOKEN`.
- [ ] **Step 5: Run tests.** Expected: 3 passed.
- [ ] **Step 6: Checkpoint:** tell the user what changed; ask before any git action.

### Task 2: Card schema and atomic store

**Files:**
- Create: `src/secondbrain/schema.py`, `src/secondbrain/store.py`, `tests/test_schema.py`, `tests/test_store.py`, `schemas/card.v1.json` (generated)

**Interfaces:**
- Produces (schema.py): `TOPICS: frozenset[str]` = `ai/claude-tips, ai/agents, ai/llm-engineering, ai/tools, ai/news, infra/devops, infra/sre, infra/platform, infra/cloud, infra/security-finops, business/startup-stories, business/product, business/saas-pricing, business/money, marketing/audience, marketing/sales, marketing/positioning, growth/habits, growth/focus, growth/mindset, growth/health, career/remote-jobs, career/strategy, career/engineering, noise/entertainment, uncertain`; `FORMATS: frozenset[str]` = `tip, tutorial, podcast, talk, news, case-study, opinion, review`; `CARD_TYPES` = `consumed, thought, decided, acted, produced, experiment, friction, book, link`; `validate_topic(t: str) -> str` (returns `t` if in TOPICS else `"uncertain"`); models `KeyPoint(text, topic, t: str | None, confidence: float 0-1)`, `Relevance(bet_job, bet_product, actionability, novelty, quality: int 0-10, score: int 0-100)`, `Card` (fields exactly as the design's card.v1 example; `visibility` default `"private"`, `tier` default `"hot"`, `schema` default `"card.v1"`), `Tombstone(id, source, title, url, date, topic, score)`; `export_json_schema(path: Path) -> None`.
- Produces (store.py): `Store(root: Path)` with `has(id) -> bool` (card or tombstone), `write_card(card: Card) -> Path` (path `cards/YYYY/MM/<id>.json` from `consumed_at`; writes temp file then `os.replace`), `write_tombstone(t: Tombstone) -> None` (appends a line to `archive/tombstones.jsonl`; no duplicate id), `read_card(id) -> Card`, `iter_cards() -> Iterator[Card]`.

- [ ] **Step 1: Failing tests (schema):** `test_card_defaults_to_private_hot`; `test_validate_topic_unknown_returns_uncertain` (`validate_topic("ai/magic") == "uncertain"`, `validate_topic("infra/sre") == "infra/sre"`); `test_relevance_rejects_score_over_100`; `test_confidence_rejects_above_one`.
- [ ] **Step 2: Failing tests (store):** `test_write_card_creates_dated_path` (file at `cards/2026/11/yt_abc.json`); `test_write_card_is_atomic` (monkeypatch `os.replace` to raise; the final path does not exist and no `.tmp` file remains); `test_write_tombstone_twice_one_line`; `test_has_true_for_card_and_tombstone`; `test_iter_cards_roundtrip`.
- [ ] **Step 3: Run** `pytest tests/test_schema.py tests/test_store.py -v`. Expected: FAIL.
- [ ] **Step 4: Implement** both modules. Pydantic `ConfigDict(extra="forbid")`. `export_json_schema` writes `Card.model_json_schema()`.
- [ ] **Step 5: Run tests.** Expected: all pass. Generate `schemas/card.v1.json`.
- [ ] **Step 6: Checkpoint.**

### Task 3: Takeout adapter

**Files:**
- Create: `src/secondbrain/adapters/__init__.py`, `src/secondbrain/adapters/takeout.py`, `tests/test_takeout.py`, `tests/fixtures/watch-history.json`

**Interfaces:**
- Produces: `@dataclass(frozen=True) WatchItem(video_id: str, title: str, url: str, channel: str | None, watched_at: datetime)`; `parse_takeout(path: Path) -> list[WatchItem]` (newest first, one per video id, keeping the latest watch).

- [ ] **Step 1: Fixture** with 6 entries: a normal video, the same video watched twice, an entry with no `titleUrl` (removed video), an ad entry (`details: [{"name":"From Google Ads"}]`), a community post URL (`/post/...`), a title with emoji and Hindi text.
- [ ] **Step 2: Failing tests:** `test_parses_normal_video` (video_id from `?v=`, title with the "Watched " prefix stripped, channel from `subtitles[0].name`, tz-aware datetime); `test_dedupes_keeping_latest`; `test_skips_missing_url_ads_and_posts` (result length 2 on the fixture); `test_unicode_title_preserved`; `test_malformed_file_raises_value_error_with_path`.
- [ ] **Step 3: Run.** Expected: FAIL.
- [ ] **Step 4: Implement** `parse_takeout` (stdlib `json`).
- [ ] **Step 5: Run.** Expected: 5 passed.
- [ ] **Step 6: Checkpoint.**

### Task 4: Transcripts

**Files:**
- Create: `src/secondbrain/transcripts.py`, `tests/test_transcripts.py`

**Interfaces:**
- Produces: `@dataclass Segment(start: float, text: str)`; `@dataclass Transcript(video_id: str, language: str, segments: list[Segment])`; `get_transcript(video_id: str, cache_dir: Path, fetcher: Callable[[str], Transcript] | None = None, max_retries: int = 2, sleep: Callable[[float], None] = time.sleep) -> Transcript | None`; `to_text(t: Transcript, with_times: bool = False) -> str` (with times: `[mm:ss] text` lines); `chunk(t: Transcript, max_chars: int = 24000) -> list[str]` (split on segment boundaries, never mid-segment).
- Fetcher raises `TranscriptUnavailable` (disabled or none) or `RateLimited`. Default fetcher wraps `youtube-transcript-api`.

- [ ] **Step 1: Failing tests (fake fetcher):** `test_returns_none_when_unavailable`; `test_cache_hit_skips_fetch` (fetcher called once across two calls; cache file `raw/transcripts/<id>.json`); `test_rate_limit_retries_then_gives_up` (max_retries=2 gives 3 fetch attempts, `sleep` called with increasing delays, returns None); `test_to_text_with_times_format` (`[01:05] hello`); `test_chunk_never_splits_segment_and_respects_limit`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** Exponential backoff `2**attempt` seconds. A negative result (unavailable) is also cached so it is not re-fetched.
- [ ] **Step 4: Run.** Expected: 5 passed.
- [ ] **Step 5: Checkpoint.**

### Task 5: LLM providers and sensitivity routing

**Files:**
- Create: `src/secondbrain/llm.py`, `tests/test_llm.py`

**Interfaces:**
- Produces: `Provider` Protocol with `name: str`, `is_local: bool`, `complete(prompt: str, *, system: str | None = None) -> str`; `OllamaProvider(base_url="http://localhost:11434", model: str, client: httpx.Client | None = None)` (`is_local=True`, POST `/api/generate`, `stream=False`); `OpenAICompatProvider(base_url: str, api_key: str, model: str, client: httpx.Client | None = None)` (`is_local=False`, POST `/chat/completions`; works for Groq, Gemini's OpenAI endpoint, NVIDIA); `complete_json(provider: Provider, prompt: str, model_cls: type[T], retries: int = 1) -> T` (extracts the first JSON object from the reply, validates; on failure retries once with the validation error appended, then raises `LLMOutputError`); `Router(routes: dict[str, Provider])` with `route(task: str, sensitivity: Literal["public", "private"]) -> Provider` raising `SensitivityError` if sensitivity is `private` and the provider is not local, and `KeyError` for unknown task. Task names: `triage`, `extract`, `synthesis`. Also `build_router(env: Mapping[str, str]) -> Router`: reads `SB_ROUTE_TRIAGE`, `SB_ROUTE_EXTRACT`, `SB_ROUTE_SYNTHESIS` (values `ollama`, `groq`, `gemini`, `nvidia`) plus each provider's model and key variables from `.env.example`; a route naming a provider with a missing key raises `ConfigError` (used by `sb ingest` in Task 15).

- [ ] **Step 1: Failing tests** using `httpx.MockTransport`: `test_ollama_sends_prompt_and_returns_text`; `test_openai_compat_sends_bearer_and_parses_choice`; `test_complete_json_parses_fenced_json`; `test_complete_json_retries_once_then_raises` (two invalid replies give `LLMOutputError`, exactly 2 calls); `test_route_private_to_cloud_raises_sensitivity_error`; `test_route_public_to_cloud_ok`; `test_api_key_not_in_error_messages`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** Timeouts 120 s for local, 60 s for cloud.
- [ ] **Step 4: Run.** Expected: 7 passed.
- [ ] **Step 5: Checkpoint.**

### Task 6: Claude usage experiment (decision gate, manual)

**Files:**
- Create: `src/secondbrain/cli.py` (first command only), `tests/test_cli_export_batch.py`, `docs/experiments/2026-claude-usage.md`

**Interfaces:**
- Produces: CLI `sb export-batch --takeout <file> --n 10 --out raw/experiment/` writing `N` transcript text files (mixed lengths: shortest, median, longest picks) plus `manifest.json` (video_id, title, minutes, chars). Function `export_batch(items: list[WatchItem], n: int, out: Path, cache_dir: Path, fetch=get_transcript) -> list[Path]`.
- Consumes: `parse_takeout`, `get_transcript`, `to_text`.

- [ ] **Step 1: Failing test** `test_export_batch_picks_n_mixed_lengths_and_skips_missing` (fake fetch; 12 items, 2 without transcripts, `n=10` gives 10 files + manifest; picks include the shortest and longest).
- [ ] **Step 2: Run.** FAIL. **Step 3: Implement** `export_batch` and the `sb` entry point. **Step 4: Run.** PASS.
- [ ] **Step 5 (user action): Request the YouTube Takeout export** (JSON, YouTube history only) and place it under `raw/takeout/`.
- [ ] **Step 6: Measure (fresh Claude session).** Record the five-hour and weekly usage readings in `docs/experiments/2026-claude-usage.md`; have Claude extract key points for the 10-file batch; read usage again; compute percent per video and at 10 videos/day. Repeat once with 3 files through headless `claude -p` and record which pool (subscription limits or separate credit pool) moved.
- [ ] **Step 7: Quality check:** spot-check 5 extractions against the transcripts; run the same batch on the local model (after the user approves installing Ollama and one model) and compare.
- [ ] **Step 8: Decide** per the rule in `docs/design.md` Stage 0b and write Plan A or Plan B into `.env` (`SB_ROUTE_EXTRACT`, `SB_ROUTE_SYNTHESIS`). Show the user the numbers and wait for his confirmation.
- [ ] **Step 9: Checkpoint.**

### Task 7: Triage and deterministic scoring

**Files:**
- Create: `src/secondbrain/triage.py`, `tests/test_triage.py`

**Interfaces:**
- Produces: `SubScores(bet_job: int, bet_product: int, actionability: int, novelty: int, quality: int)` (each 0-10); `compute_score(sub: SubScores, topic: str) -> int` = `round(10 * (0.5 * max(bet_job, bet_product) + 0.2 * actionability + 0.15 * novelty + 0.15 * quality))`, capped at 20 when `topic == "noise/entertainment"`; `KEEP_THRESHOLD = 40`; `TriageResult(topic: str, format: str, sub: SubScores, score: int, keep: bool)`; `triage(item: WatchItem, transcript_head: str | None, goals_text: str, llm: Provider) -> TriageResult` (prompt includes goals, taxonomy topic list, title, channel, first 2000 chars of transcript; reply parsed with `complete_json`; unknown topic -> `uncertain`; unknown format -> `opinion`; scores clamped by validation, not by silent clipping).

- [ ] **Step 1: Failing tests:** `test_compute_score_example` (job=8, product=3, act=6, nov=5, qual=7 -> 70); `test_compute_score_all_ten_is_100`; `test_entertainment_capped_at_20` (all tens, topic `noise/entertainment` -> 20); `test_keep_threshold_boundary` (score 40 keeps, 39 does not); `test_triage_unknown_topic_becomes_uncertain` (fake provider returns topic "ai/magic"); `test_triage_invalid_json_raises_llm_output_error`; `test_triage_without_transcript_uses_title_and_channel_only` (prompt contains title, no transcript block).
- [ ] **Step 2: Run.** FAIL. **Step 3: Implement.** **Step 4: Run.** 7 passed. **Step 5: Checkpoint.**

### Task 8: Extraction

**Files:**
- Create: `src/secondbrain/extract.py`, `tests/test_extract.py`

**Interfaces:**
- Produces: `Extraction(key_points: list[KeyPoint], action: Action | None)`; `extract(item: WatchItem, transcript: Transcript, llm: Provider) -> Extraction` (chunks via `chunk`, one LLM call per chunk, merges, keeps at most 7 key points by confidence, topics validated with `validate_topic`, timestamps kept as `mm:ss` when the model provides them; `action` is at most one concrete step or None).
- Consumes: `chunk`, `to_text(with_times=True)`, `complete_json`, `validate_topic`.

- [ ] **Step 1: Failing tests:** `test_extract_merges_chunks_and_caps_at_seven`; `test_extract_validates_topics` (unknown -> `uncertain`); `test_extract_empty_transcript_returns_no_key_points_without_llm_call`; `test_extract_llm_failure_raises_llm_output_error`.
- [ ] **Step 2-4:** Run to FAIL, implement, run to PASS. **Step 5: Checkpoint.**

### Task 9: Idempotent ingest pipeline

**Files:**
- Create: `src/secondbrain/pipeline.py`, `tests/test_pipeline.py`

**Interfaces:**
- Produces: `IngestReport(new_cards: int, tombstones: int, skipped_existing: int, failures: list[tuple[str, str]])`; `run_ingest(items: list[WatchItem], store: Store, router: Router, goals_text: str, cache_dir: Path, fetch=get_transcript, limit: int | None = None) -> IngestReport`.
- Consumes: `Store.has/write_card/write_tombstone`, `Router.route("triage"|"extract", sensitivity="public")`, `triage`, `extract`, `get_transcript`.
- Behavior: skip ids already in the store; triage; if not keep, write tombstone; else extract and write a card (`type=consumed`, `visibility=private`, `provenance.transcript` = `captions` or `none`); a transcript-less keeper becomes a card with empty `key_points`; per-item exceptions are recorded in `failures` and the loop continues.

- [ ] **Step 1: Failing tests (fake router and providers):** `test_second_run_makes_no_new_cards_and_no_llm_calls`; `test_low_score_item_becomes_tombstone_without_extract_call`; `test_missing_transcript_keeper_gets_card_with_provenance_none`; `test_one_failing_item_does_not_stop_the_run` (failures has 1 entry, others written); `test_interrupted_run_resumes` (raise `KeyboardInterrupt` on item 3; no `.tmp` files; rerun completes the rest with no duplicates); `test_limit_stops_after_n_new_items`.
- [ ] **Step 2-4:** FAIL, implement, PASS. **Step 5: Checkpoint.**

### Task 10: Embeddings and hybrid search index

**Files:**
- Create: `src/secondbrain/embed.py`, `src/secondbrain/index.py`, `tests/test_index.py`

**Interfaces:**
- Produces: `Embedder` Protocol `embed(texts: list[str]) -> list[list[float]]`; `FastEmbedder(model="BAAI/bge-small-en-v1.5")` (user's own download, approval first); `HashEmbedder(dim=64)` (deterministic, tests); `Index(db_path: Path, embedder: Embedder)` with `rebuild(store: Store) -> int` (drops and recreates tables; FTS5 table over title + key point text; vectors stored as blobs), `search(query: str, k: int = 5, per_source_cap: int = 3) -> list[Hit]`, `Hit(card_id: str, title: str, snippet: str, score: float)`.
- Ranking: `0.5 * normalized_bm25 + 0.5 * cosine`, times `(0.5 + relevance.score / 200)`; after ranking, at most `per_source_cap` hits per `source`.

- [ ] **Step 1: Failing tests (HashEmbedder, tmp store):** `test_rebuild_counts_cards`; `test_search_finds_keyword_match_first`; `test_higher_relevance_card_outranks_equal_text_match`; `test_per_source_cap_enforced` (6 youtube + 1 book matches, k=6, cap 3 -> at most 3 youtube); `test_rebuild_is_repeatable_after_deleting_db`.
- [ ] **Step 2-4:** FAIL, implement, PASS. **Step 5 (slow, optional, after approval):** one test marked `@pytest.mark.slow` loads the real model and checks a semantic match. **Step 6: Checkpoint.**

### Task 11: Fixed-budget context pack

**Files:**
- Create: `src/secondbrain/context.py`, `tests/test_context.py`

**Interfaces:**
- Produces: `build_context(question: str, index: Index, profile_path: Path, max_chars: int = 8000) -> str` = profile text (truncated to 3000 chars) + the top hits formatted as `- [id] title: key point` until `max_chars`.

- [ ] **Step 1: Failing tests:** `test_context_length_bounded_with_1000_cards` (`len <= 8000`); `test_context_contains_profile_and_top_hit`; `test_missing_profile_file_returns_hits_only`.
- [ ] **Step 2-4:** FAIL, implement, PASS. **Step 5: Checkpoint.**

### Task 12: Quick-capture parser

**Files:**
- Create: `src/secondbrain/bot/__init__.py`, `src/secondbrain/bot/capture.py`, `tests/test_capture.py`

**Interfaces:**
- Produces: `parse_capture(text: str, now: datetime) -> Card`. Prefix (case-insensitive) sets `type`: `book:` -> book, `idea:` -> thought, `friction:` -> friction, `experiment:` -> experiment, `decided:` -> decided, `done:` -> acted, `made:` -> produced; a message that is only a URL -> `link`; anything else -> thought. `source="telegram"`, `visibility="private"`, id `tg_<unix-seconds>_<4 hex of hash(text)>`, key point = the text after the prefix, `book:` splits on `|` into idea and action.

- [ ] **Step 1: Failing tests:** one per prefix (type and text); `test_book_splits_idea_and_action` (`"book: Zero to One | monopoly beats competition | pick a niche"` -> key point "monopoly beats competition", action "pick a niche"); `test_url_only_is_link`; `test_unprefixed_is_thought`; `test_visibility_is_always_private`; `test_empty_text_raises_value_error`.
- [ ] **Step 2-4:** FAIL, implement, PASS. **Step 5: Checkpoint.**

### Task 13: Morning brief and evening check-in builders

**Files:**
- Create: `src/secondbrain/bot/brief.py`, `tests/test_brief.py`

**Interfaces:**
- Produces: `Brief(text: str, action_id: str | None, buttons: list[tuple[str, str]])` (button = label and callback data `done:<id>`, `later:<id>`, `skip:<id>`); `build_morning_brief(store: Store, goals_text: str, now: datetime) -> Brief` (goal line, up to 3 lines from yesterday's kept cards by score, exactly ONE produce action chosen from open `action`s on the highest-scoring recent cards, else a fixed fallback "Ship one small thing today: a commit, a note, or a message to a person."; no private card text beyond titles); `build_evening_checkin(now: datetime) -> Brief` (asks what he produced and read; no buttons); `apply_feedback(store: Store, callback_data: str) -> None` (sets `card.action.status` and `card.user.acted`).

- [ ] **Step 1: Failing tests:** `test_morning_brief_has_exactly_one_action`; `test_brief_without_cards_uses_fallback_action`; `test_brief_lists_at_most_three_yesterday_items`; `test_brief_excludes_noise_and_tombstones`; `test_apply_feedback_done_marks_acted`; `test_apply_feedback_unknown_id_is_noop`.
- [ ] **Step 2-4:** FAIL, implement, PASS. **Step 5: Checkpoint.**

### Task 14: Telegram bot runtime with owner allowlist

**Files:**
- Create: `src/secondbrain/bot/app.py`, `tests/test_bot_app.py`
- Modify: `src/secondbrain/cli.py` (add `sb bot`)

**Interfaces:**
- Produces: `is_owner(update: Update, owner_id: int | None) -> bool` (False when `owner_id` is None); `build_application(token: str, owner_id: int, store: Store, goals_text: str) -> Application` with handlers: text message -> `parse_capture` -> `store.write_card` -> reply "Saved: <type>"; callback queries -> `apply_feedback`; `/brief` -> morning brief; `/evening` -> evening check-in; scheduled jobs: morning brief at first run after 09:00 local if not yet sent that day, evening check-in at 21:30.
- Every handler returns immediately without reply or write when `is_owner` is False. The token is read from settings only and never logged.

- [ ] **Step 1: Failing tests (fake `Update` objects):** `test_non_owner_message_gets_no_reply_and_no_card` (Review Focus 2); `test_owner_message_creates_card_and_replies`; `test_non_owner_callback_ignored`; `test_owner_id_none_rejects_everyone`; `test_token_not_logged` (caplog contains no token string).
- [ ] **Step 2-4:** FAIL, implement, PASS.
- [ ] **Step 5 (user action):** create the bot with BotFather, put the token and his Telegram user id in `.env`. Run `sb bot` and confirm: his message is saved as a card; a message from another account is ignored.
- [ ] **Step 6: Checkpoint.**

### Task 15: Autostart and end-to-end acceptance

**Files:**
- Create: `scripts/install-autostart.ps1`, `tests/test_cli_ingest.py`
- Modify: `src/secondbrain/cli.py` (add `sb ingest --takeout <file> [--limit N]` and `sb search "<query>"`)

**Interfaces:**
- Produces: `sb ingest` runs `parse_takeout` -> `run_ingest` -> `Index.rebuild` and prints the `IngestReport`; `sb search` prints top hits; `install-autostart.ps1` registers a Task Scheduler task "SecondBrainBot" at logon that runs `.venv\Scripts\python -m secondbrain.cli bot`, with "run as soon as possible after a missed start" and no network-idle condition.

- [ ] **Step 1: Failing test:** `test_ingest_command_end_to_end_with_fake_providers` (fixture Takeout + fake router: report counts correct, `cards/` populated, index searchable, second invocation reports all skipped).
- [ ] **Step 2-4:** FAIL, implement, PASS.
- [ ] **Step 5 (acceptance, manual):** run `sb ingest --takeout raw/takeout/watch-history.json --limit 100`; confirm about 100 items processed at zero cost; spot-check 20 cards (key points correct, topic right); note errors in `docs/experiments/stage1-spot-check.md`.
- [ ] **Step 6 (user approval first):** run `install-autostart.ps1`; reboot; confirm the bot is running and the morning brief arrives on first unlock.
- [ ] **Step 7:** Start the 14-day stop-rule clock. Record the start date in `docs/decisions.md`.
- [ ] **Step 8: Checkpoint.**

---

## Self-Review notes

- Spec coverage: Stage 0b (Task 6), Stage 1 (Tasks 1-5, 7-11, 15), Stage 2 (Tasks 12-14, 15). Not in this plan: weekly review, lifecycle and consolidation, resurfacing, book and experiment workflows beyond capture, publishable feed, AI-chat ingestion, yt-dlp automation, evaluation set, cognee, opportunity finder. These belong to the next plan (Stages 3-5).
- Type consistency: `Store`, `Router`, `Provider`, `WatchItem`, `Transcript`, `Card` are defined once (Tasks 2-5) and referenced by the same names later.
- Design doc's example card shows relevance score 62; with the Task 7 formula the same sub-scores give 65. The example is illustrative; the formula in Task 7 is authoritative.
