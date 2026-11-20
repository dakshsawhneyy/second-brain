# Second Brain, Stages 3-5 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the memory lean and useful as it grows (lifecycle, themes, weekly review, resurfacing), add belief auditing, a publishable feed for his X/LinkedIn tools, AI-chat ingestion, and a retrieval evaluation set.

**Architecture:** New small modules next to the existing ones: `lifecycle`, `metrics`, `themes`, `resurface`, `beliefs`, `feed`, `chats`, `evals`, `usage`. They read and write the same card store and use the same `Router` privacy gate. The Telegram scheduler is generalised from two hard-coded jobs to named job builders so the weekly review, resurfacing and belief audit plug in.

**Tech Stack:** Same as Stages 0b-2 (Python 3.12, pydantic v2, httpx, sqlite3 FTS5, fastembed, python-telegram-bot, pytest). No new dependencies.

**Spec:** `docs/design.md` (sections 5, 5b, 5c, 6, 7, 8). Companions: `docs/decisions.md`, `docs/taxonomy.md`, `docs/NEXT_STEPS.md`, `docs/ledger.md` (rulings and deferred minors of the first plan).

**Prerequisite:** Stages 0b-2 are built (266 tests). The Task 6 usage experiment and the first real 100-video ingest (docs/NEXT_STEPS.md, section A) should be done before Tasks 13-14 and Task 15, which need real data. Tasks 1-12 can be built on fixtures.

## Global Constraints

- Python 3.12, Windows 11, laptop only, zero cost, no new paid services or dependencies without his approval.
- Never modify or depend on SkipATS (`C:\Studies\Claude Code\startup_finder`). Read-only toward his other apps.
- No `git add`, `commit` or `push` without his explicit approval each time. Checkpoint steps only record results in `docs/ledger.md`.
- Private data (his goals, thoughts, chat content, themes, beliefs) goes only to a local model: use `router.route(task, "private")`. Nothing private in a prompt to a cloud model.
- Cards default to `visibility="private"`. Only an explicit publish action makes a card publishable.
- Telegram is not end-to-end encrypted: messages show counts, titles, one action, or one YouTube-derived key point. Never goals, thoughts, chat text, belief text from private chats, or key points of `thought`/`book`/`decided` cards.
- Never overwrite his hand-written `profile/profile.md` or `profile/goals.md`. Generated files are separate.
- Secrets live only in `.env`. Chat imports are scrubbed of secrets before anything is stored.
- Every file write is atomic (temp file then `os.replace`), and every job is safe to re-run.
- Taxonomy and topic ids exactly as in `src/secondbrain/schema.py`.

## Review Focus

1. **Data loss on demotion:** a crash between writing the tombstone and deleting the card, or demoting a card he acted on, rated, or wrote himself. Expected: tombstone first, then delete; protected cards never auto-demoted. (Tasks 1, 2)
2. **Publishable feed leak:** a private card, a private field (ratings, tier, sub-scores, user signals) or malformed card reaching `feed/publishable.jsonl`. Expected: only `visibility == "publishable"`, only whitelisted public fields, fails closed. (Task 12)
3. **Private text in Telegram or on a cloud model:** the weekly review, resurfacing, belief audit or theme jobs exposing thought/book/chat text or sending it to a non-local provider. Expected: counts and titles only (plus one YouTube key point in resurfacing); local-only routes; `SensitivityError` otherwise. (Tasks 5, 7, 8, 10)
4. **Chat export hazards:** secrets pasted into chats, assistant messages stored as his words, huge or malformed files, re-import duplicates. Expected: redaction before storage, user side only, bounded input, idempotent ids. (Tasks 13, 14)
5. **Overwritten or hallucinated memory:** an LLM theme, belief or profile update replacing good data when the model fails or invents evidence. Expected: failed generation leaves previous files untouched; evidence ids must exist; hand-written files never changed. (Tasks 5, 10)

---

## File Structure

```
src/secondbrain/
  lifecycle.py   tier policy, demotion run, raw-transcript purge
  usage.py       UsageLoggingProvider and weekly usage summary
  metrics.py     weekly numbers from cards and tombstones
  themes.py      weekly and monthly themes (local model), Claude packet export/import
  resurface.py   pick an old insight and track cooldowns
  beliefs.py     belief store, proposals, confirm/reject, challenge
  feed.py        publishable feed export, publish/unpublish
  chats.py       ChatGPT and Claude export parsers, secret redaction, digest ingest
  evals.py       retrieval evaluation set
  store.py       (modify) iter_tombstones, remove_tombstone, demote_to_tombstone
  llm.py         (modify) build_router(env, usage_log=None)
  context.py     (modify) optional beliefs section
  bot/capture.py (modify) structured experiment capture
  bot/brief.py   (modify) weekly review builder, rescue/used/archive/belief feedback
  bot/app.py     (modify) named job builders, weekly and resurfacing jobs, /challenge
  cli.py         (modify) sb lifecycle|week|import-theme|publish|unpublish|export-feed|ingest-chats|eval
themes/weekly/YYYY-Www.json, themes/monthly/YYYY-MM.json, profile/beliefs.json,
feed/publishable.jsonl, schemas/feed.v1.json, docs/evals/questions.json
tests/test_<module>.py per module
```

---

### Task 1: Store demotion and tombstone helpers

**Files:**
- Modify: `src/secondbrain/store.py`
- Test: `tests/test_store_demote.py`

**Interfaces:**
- Produces on `Store`: `iter_tombstones() -> Iterator[Tombstone]` (skips unreadable lines); `remove_tombstone(id: str) -> bool` (rewrites `archive/tombstones.jsonl` atomically without that id; True if it existed); `demote_to_tombstone(id: str) -> Tombstone` (reads the card, writes the tombstone first (`date = consumed_at.date()`, `topic = topic.primary`, `score = relevance.score or 0`), then deletes the card file; raises `KeyError` if missing; if the tombstone write fails the card stays).

- [ ] **Step 1: Failing tests:** `test_demote_writes_tombstone_then_deletes_card` (card gone, `has(id)` True, tombstone fields match); `test_demote_failure_after_tombstone_leaves_both_and_rerun_is_safe` (monkeypatch card unlink to raise; rerun completes, one tombstone line); `test_demote_failure_before_tombstone_keeps_the_card` (monkeypatch tombstone write to raise; card file still exists); `test_demote_unknown_id_raises_key_error`; `test_iter_tombstones_skips_corrupt_lines`; `test_remove_tombstone_rewrites_atomically_and_reports_existence`; `test_demote_card_without_relevance_uses_score_zero`.
- [ ] **Step 2: Run** `.venv\Scripts\python -m pytest tests/test_store_demote.py -v`. Expected: FAIL (methods missing).
- [ ] **Step 3: Implement** the three methods; reuse the existing atomic-write pattern.
- [ ] **Step 4: Run the whole suite.** Expected: all pass.
- [ ] **Step 5: Checkpoint** (ledger line; no git).

### Task 2: Lifecycle policy, run and raw purge

**Files:**
- Create: `src/secondbrain/lifecycle.py`
- Test: `tests/test_lifecycle.py`

**Interfaces:**
- Consumes: `Store.iter_cards/write_card/demote_to_tombstone`.
- Produces: constants `HOT_DAYS=14`, `DEMOTE_AFTER_DAYS=21`, `WARM_MIN_SCORE=50`, `THEME_GRACE_DAYS=60`, `RAW_MAX_AGE_DAYS=30`; `is_protected(card: Card) -> bool` (True if `type != "consumed"`, or `user.rating` or `user.acted` is set, or `action.status in {"open","later"}`, or `visibility == "publishable"`); `assign_tier(card: Card, now: datetime, has_theme: bool) -> Literal["hot","warm","demote"]`; `LifecycleReport(to_warm: int, demoted: list[str], purged_raw: int)`; `run_lifecycle(store: Store, now: datetime, has_theme: Callable[[Card], bool], raw_dir: Path | None = None) -> LifecycleReport`; `purge_raw(raw_dir: Path, now: datetime, max_age_days: int = RAW_MAX_AGE_DAYS) -> int`.
- Policy: protected cards are `hot` under 14 days else `warm`, never `demote`. Others: age < 14 -> hot; score >= 50 -> warm; score < 50 and age >= 21 and (`has_theme` or age >= 60) -> demote; otherwise warm.

- [ ] **Step 1: Failing tests:** table test for `assign_tier` with exact cases: (score 45, age 25, theme) -> demote; (45, 25, no theme) -> warm; (45, 61, no theme) -> demote; (80, 100) -> warm; (45, 10) -> hot; (45, 20, theme) -> warm; protected cases (acted=True score 5 age 200; type `thought` age 200; action open; rating 3; publishable) -> never demote. `test_run_lifecycle_updates_tiers_and_demotes_and_is_idempotent` (second run changes nothing); `test_run_lifecycle_never_touches_cold_or_protected`; `test_purge_raw_deletes_only_old_transcript_cache_files` (files under `raw/transcripts/` older than 30 days deleted; `raw/takeout/`, `raw/experiment/`, `bot_state.json` untouched); `test_purge_raw_missing_dir_is_a_noop`.
- [ ] **Step 2: Run.** FAIL. **Step 3: Implement.** **Step 4: Run whole suite.** PASS.
- [ ] **Step 5: Checkpoint.**

### Task 3: Usage log wrapper

**Files:**
- Create: `src/secondbrain/usage.py`
- Modify: `src/secondbrain/llm.py` (`build_router(env, usage_log: Path | None = None)`)
- Test: `tests/test_usage.py`

**Interfaces:**
- Produces: `UsageLoggingProvider(inner: Provider, task: str, log_path: Path)` implementing `Provider` (`name`, `is_local` forwarded from `inner`; `complete` forwards and appends one JSON line `{ts, task, provider, local, prompt_chars, reply_chars, seconds, ok}`; on exception logs `ok=false` and re-raises); `@dataclass UsageSummary(calls: int, failures: int, prompt_chars: int, reply_chars: int, local: bool)`; `summarize_usage(log_path: Path, since: datetime) -> dict[str, UsageSummary]` keyed by task.

- [ ] **Step 1: Failing tests:** `test_logs_success_and_failure_and_reraises`; `test_prompt_and_reply_text_never_written_to_the_log` (log contains only counts); `test_privacy_gate_still_blocks_through_the_wrapper` (cloud inner + `Router.route(..., "private")` raises `SensitivityError`); `test_is_local_forwarded_for_local_inner`; `test_summarize_filters_by_since_and_skips_corrupt_lines`; `test_build_router_wraps_every_route_when_log_given`.
- [ ] **Step 2-4:** FAIL, implement, PASS (whole suite). **Step 5: Checkpoint.**

### Task 4: Weekly metrics

**Files:**
- Create: `src/secondbrain/metrics.py`
- Test: `tests/test_metrics.py`

**Interfaces:**
- Consumes: `Store.iter_cards/iter_tombstones`.
- Produces: `iso_week(d: date) -> str` (`"2026-W47"`); `week_bounds(week: str) -> tuple[date, date]` (Monday, Sunday); `@dataclass WeekMetrics(week: str, watched: int, kept: int, entertainment: int, growth_share: float | None, produced: int, kept_per_produced: float | None, actions_done: int, actions_skipped: int, actions_open: int, act_rate: float | None, experiments_open: int, experiments_done: int, friction: int, top_topics: list[tuple[str, int]], uncertain: int, surprises: list[Tombstone])`; `compute_week(store: Store, week: str, tz: tzinfo) -> WeekMetrics`.
- Definitions: `watched` = consumed cards + tombstones dated in the week; `entertainment` = tombstones with topic `noise/entertainment`; `growth_share` = (watched - entertainment) / watched (None if 0); `produced` = cards of type `produced` or `acted` in the week; `kept_per_produced` = kept / produced (None if produced is 0); actions counted over cards of the week by `action.status` (`later` counts as open); `act_rate` = done / (done + skipped + open) (None if 0); `surprises` = up to 3 non-entertainment tombstones of the week by score desc; `top_topics` = top 3 primary topics among kept cards.

- [ ] **Step 1: Failing tests:** `test_iso_week_and_bounds` (2026-11-18 -> `2026-W47`, Monday 2026-11-16, Sunday 2026-11-22); `test_counts_for_a_known_week` (fixture of 10 cards and 6 tombstones with exact expected numbers); `test_ratios_are_none_when_denominator_is_zero`; `test_cards_outside_the_week_are_ignored`; `test_week_boundary_uses_the_given_timezone` (card at 2026-11-22 20:00 UTC counts in IST week W47 or W48 correctly per tz); `test_surprises_exclude_entertainment_and_are_sorted`; `test_later_status_counts_as_open`; `test_empty_store_returns_zeros_not_errors`.
- [ ] **Step 2-4:** FAIL, implement, PASS. **Step 5: Checkpoint.**

### Task 5: Themes (local generation, weekly and monthly)

**Files:**
- Create: `src/secondbrain/themes.py`
- Test: `tests/test_themes.py`

**Interfaces:**
- Consumes: `Store.iter_cards`, `Router.route("synthesis", "private")`, `complete_json`, `week_bounds`, `validate_topic`.
- Produces: `Theme(period: str, title: str, summary: str, insights: list[str] (max 5), topics: list[str] (max 3, valid topics), card_ids: list[str], generated_by: str, generated_at: datetime)` (pydantic, `extra="forbid"`); `theme_path(root: Path, period: str) -> Path` (`themes/weekly/2026-W47.json` or `themes/monthly/2026-11.json`); `load_theme(root, period) -> Theme | None`; `has_theme_for_card(root: Path, card: Card) -> bool` (weekly theme of the card's ISO week exists); `generate_weekly_theme(store: Store, root: Path, week: str, llm: Provider, now: datetime) -> Theme | None` (needs at least 3 kept consumed cards in that week, else None; the prompt contains titles and key-point text only; `card_ids` must be a subset of the week's ids; writes atomically; an existing theme is not overwritten); `generate_monthly_theme(root, month: str, llm, now) -> Theme | None` (built from that month's weekly themes, needs at least 2); `consolidate(store, root, router, now) -> list[str]` (generates missing themes for completed weeks and months only; per-period failure is logged and skipped).

- [ ] **Step 1: Failing tests:** `test_weekly_theme_written_with_valid_fields`; `test_fewer_than_three_cards_returns_none_and_writes_nothing`; `test_invented_card_ids_are_dropped_and_if_none_remain_returns_none` (Review Focus 5); `test_llm_failure_leaves_existing_theme_untouched_and_writes_nothing_new`; `test_existing_theme_is_not_overwritten`; `test_unknown_topics_become_uncertain_and_insights_capped_at_five`; `test_prompt_contains_no_thought_or_book_card_text` (only `consumed` youtube cards feed it); `test_consolidate_skips_the_current_week_and_current_month`; `test_cloud_synthesis_route_raises_sensitivity_error_and_writes_nothing` (Review Focus 3); `test_monthly_theme_uses_weekly_themes_and_needs_two`; `test_has_theme_for_card`.
- [ ] **Step 2-4:** FAIL, implement, PASS. **Step 5: Checkpoint.**

### Task 6: Claude-assisted weekly packet (export and import)

**Files:**
- Modify: `src/secondbrain/themes.py`, `src/secondbrain/cli.py`
- Test: `tests/test_theme_packet.py`

**Interfaces:**
- Produces: `export_week_packet(store: Store, week: str, out_dir: Path) -> Path` writing `raw/packets/weekly-<week>.md` (instructions, then titles and key points of that week's kept consumed cards, plus the exact JSON schema of `Theme` to reply with); `import_theme(root: Path, store: Store, path: Path, period: str, now: datetime) -> Theme` (validates JSON against `Theme`, drops `card_ids` not in the store, overwrites an existing theme only if `overwrite=True` is passed). CLI: `sb week-packet --week 2026-W47`, `sb import-theme FILE --period 2026-W47 [--overwrite]`. Purpose: weekly synthesis by Claude in an interactive session he starts (design 5c), without any unattended Claude call.

- [ ] **Step 1: Failing tests:** `test_packet_lists_week_cards_and_the_schema_and_nothing_private` (no thought/book cards, no goals text); `test_import_validates_and_writes_theme`; `test_import_drops_unknown_card_ids`; `test_import_rejects_invalid_json_without_writing`; `test_import_refuses_to_overwrite_without_flag`; `test_cli_parser_has_week_packet_and_import_theme`.
- [ ] **Step 2-4:** FAIL, implement, PASS. **Step 5: Checkpoint.**

### Task 7: Scheduler job builders and the weekly review

**Files:**
- Modify: `src/secondbrain/bot/brief.py`, `src/secondbrain/bot/app.py`, `tests/test_bot_app.py`, `tests/test_brief.py`
- Test: `tests/test_weekly_review.py`

**Interfaces:**
- Produces (brief.py): `build_weekly_review(metrics: WeekMetrics, theme: Theme | None, usage: dict[str, UsageSummary] | None) -> Brief` (plain text: watched/kept/entertainment and growth share, produced and kept-per-produced ("nothing produced yet" if None), actions done/skipped/open and act rate, experiments open/done, top topics, count of cards needing a topic, theme title only, model-call counts per task, and "Might have been dropped by mistake:" with up to 3 surprise titles and buttons `("Rescue 1", "rescue:<id>")` ...; no key-point text; at most 4096 chars); `apply_feedback` extended with `rescue:<id>` (calls `store.remove_tombstone`, so the next ingest re-processes that video). Callback data stays <= 64 bytes.
- Produces (app.py): `due_jobs(now, state) -> list[str]` also returns `"weekly"` on Sunday 10:00-22:00 once per ISO week (state value `"2026-W47"`); `run_due_jobs(send, builders: dict[str, Callable[[], Brief | None]], now, state_path)` replaces the old signature: jobs run in the order returned by `due_jobs`, a builder returning None means "nothing to send" and is still marked done for the period, a failed send is retried next tick. The `weekly` builder first runs `consolidate` then `run_lifecycle` (using `has_theme_for_card`), then computes metrics and builds the review.
- Existing morning and evening behaviour and windows stay exactly as they are.

- [ ] **Step 1: Failing tests:** `test_weekly_review_text_has_numbers_and_no_key_point_text` (cards carry the marker `SECRET-DETAIL`; absent from text); `test_review_shows_nothing_produced_yet_when_none`; `test_review_stays_under_4096_chars_with_extreme_titles`; `test_review_buttons_are_rescue_with_ids_under_64_bytes`; `test_rescue_feedback_removes_tombstone_and_unknown_id_is_a_noop`; `test_due_jobs_weekly_only_on_sunday_window_and_once_per_week` (Saturday 23:00 no; Sunday 09:59 no; Sunday 10:00 yes; Sunday 22:00 no; state `2026-W47` suppresses; next Sunday yes); `test_run_due_jobs_with_builders_sends_in_order_marks_state_and_retries_failed_send`; `test_builder_returning_none_marks_done_without_sending`; `test_weekly_builder_runs_consolidate_then_lifecycle_before_metrics` (order recorded by fakes); all existing scheduler tests updated to the new signature and still green.
- [ ] **Step 2-4:** FAIL, implement, PASS (whole suite). **Step 5: Checkpoint.**

### Task 8: Resurfacing

**Files:**
- Create: `src/secondbrain/resurface.py`
- Modify: `src/secondbrain/bot/brief.py` (`used:`, `notyet:`, `archive:` feedback), `src/secondbrain/bot/app.py` (job `"resurface"`)
- Test: `tests/test_resurface.py`

**Interfaces:**
- Produces: constants `MIN_AGE_DAYS=14`, `MIN_SCORE=60`, `COOLDOWN_DAYS=30`; `load_cooldowns(path: Path) -> dict[str, str]`, `save_cooldowns(path, data)` (atomic, corrupt file -> `{}`); `pick_resurface(cards: Iterable[Card], cooldowns: dict[str, str], now: datetime, rng: random.Random) -> Card | None` (only `source == "youtube"`, `type == "consumed"`, with at least one key point, age >= 14 days, score >= 60, not acted on, not in cooldown; weighted by score); `build_resurface(card: Card) -> Brief` (title, the single highest-confidence key point, "Did you use it?", buttons `used:<id>`, `notyet:<id>`, `archive:<id>`).
- Feedback: `used` -> `user.acted=True`; `notyet` -> no change except the cooldown being recorded by the job; `archive` -> `store.demote_to_tombstone` (explicit user request overrides protection).
- Job `"resurface"`: daily 17:00-21:00, once per day.

- [ ] **Step 1: Failing tests:** `test_pick_excludes_young_low_score_acted_cooldown_non_youtube_and_no_key_points`; `test_pick_is_deterministic_with_seeded_rng_and_weighted_toward_higher_score` (10 000 draws, ratio within tolerance); `test_pick_returns_none_when_nothing_eligible`; `test_build_resurface_shows_one_key_point_only_and_title`; `test_used_marks_acted_archive_demotes_notyet_noop`; `test_cooldown_file_roundtrip_and_corrupt_file`; `test_due_jobs_resurface_window_and_once_per_day`.
- [ ] **Step 2-4:** FAIL, implement, PASS. **Step 5: Checkpoint.**

### Task 9: Structured experiment capture

**Files:**
- Modify: `src/secondbrain/bot/capture.py`
- Test: extend `tests/test_capture.py`

**Interfaces:**
- `experiment: <hypothesis> | <cheapest test>` -> card type `experiment`, title = hypothesis (flattened, <= 80), key point = hypothesis, `action` = the test (`status="open"`), so the existing morning-brief logic can offer it. `experiment: <text>` without `|` keeps today's behaviour. New prefix `result: <text>` -> type `decided`. Everything else unchanged.

- [ ] **Step 1: Failing tests:** `test_experiment_with_pipe_sets_hypothesis_and_open_action`; `test_experiment_without_pipe_unchanged`; `test_experiment_with_empty_test_part_has_no_action`; `test_result_prefix_creates_decided_card`; `test_experiment_action_can_be_chosen_by_the_morning_brief` (integration with `build_morning_brief`).
- [ ] **Step 2-4:** FAIL, implement, PASS. **Step 5: Checkpoint.**

### Task 10: Beliefs and belief audit

**Files:**
- Create: `src/secondbrain/beliefs.py`
- Modify: `src/secondbrain/bot/brief.py` (`bconfirm:` / `breject:` feedback), `src/secondbrain/bot/app.py` (weekly job also sends the audit)
- Test: `tests/test_beliefs.py`

**Interfaces:**
- Produces: `Belief(id: str, text: str (<= 200), evidence: list[str] (<= 10 card ids), status: Literal["proposed","confirmed","rejected"], created_at: datetime)`; `load_beliefs(path: Path) -> list[Belief]` and `save_beliefs(path, beliefs)` (atomic; corrupt file -> `[]` and the corrupt file is kept as `beliefs.json.bad`); `propose_beliefs(themes: list[Theme], thoughts: list[Card], existing: list[Belief], llm: Provider, now: datetime, known_ids: set[str]) -> list[Belief]` (at most 5, status `proposed`; evidence ids not in `known_ids` are dropped and a belief left with no evidence is discarded; texts equal (case/space-insensitive) to an existing belief of any status are skipped; the prompt is built from theme summaries and the user's own `thought`/`decided` cards, and the provider must be local); `set_status(path: Path, belief_id: str, status: str) -> bool`; `build_belief_audit(beliefs: list[Belief]) -> Brief | None` (the first proposed belief only, text shown, buttons `bconfirm:<id>` / `breject:<id>`).
- Never writes `profile/profile.md`. Confirmed beliefs live in `profile/beliefs.json`.

- [ ] **Step 1: Failing tests:** `test_proposals_capped_at_five_and_status_proposed`; `test_invented_evidence_dropped_and_evidenceless_belief_discarded` (Review Focus 5); `test_duplicates_of_existing_beliefs_skipped_even_if_rejected`; `test_cloud_provider_raises_sensitivity_error_via_router` (Review Focus 3); `test_llm_failure_returns_empty_and_does_not_touch_the_file`; `test_set_status_and_feedback_roundtrip`; `test_corrupt_beliefs_file_is_preserved_as_bad_and_treated_as_empty`; `test_audit_message_shows_one_proposed_belief_with_buttons_and_none_when_nothing_proposed`; `test_profile_md_is_never_written` (file mtime and content unchanged).
- [ ] **Step 2-4:** FAIL, implement, PASS. **Step 5: Checkpoint.**

### Task 11: Beliefs in the context pack and challenge mode

**Files:**
- Modify: `src/secondbrain/context.py`, `src/secondbrain/bot/app.py`
- Test: extend `tests/test_context.py`, new `tests/test_challenge.py`

**Interfaces:**
- `build_context(question, index, profile_path, max_chars=8000, beliefs_path: Path | None = None) -> str`: adds a section `# What I believe (confirmed)` with confirmed beliefs (<= 1500 chars total, oldest first dropped last) between the profile and the memory lines; the total never exceeds `max_chars`; with no beliefs file the output is byte-identical to today's.
- `challenge(belief: Belief, llm: Provider) -> str` (strongest honest counter-argument, <= 600 chars, via `complete_json` or plain text trimmed); bot command `/challenge` (owner only): picks a random confirmed belief, replies with the belief and the counter-argument; local model only (`route("synthesis", "private")`); replies "No confirmed beliefs yet." when none.

- [ ] **Step 1: Failing tests:** `test_context_unchanged_without_beliefs_file`; `test_context_includes_only_confirmed_beliefs`; `test_context_with_beliefs_still_respects_max_chars_and_tiny_budgets`; `test_challenge_returns_trimmed_text_and_uses_local_route`; `test_challenge_command_owner_only_and_empty_state_message`; `test_challenge_cloud_route_refused`.
- [ ] **Step 2-4:** FAIL, implement, PASS. **Step 5: Checkpoint.**

### Task 12: Publishable feed (contract for his X and LinkedIn tools)

**Files:**
- Create: `src/secondbrain/feed.py`
- Modify: `src/secondbrain/cli.py` (`sb publish ID`, `sb unpublish ID`, `sb export-feed`)
- Output: `feed/publishable.jsonl`, `schemas/feed.v1.json`
- Test: `tests/test_feed.py`

**Interfaces:**
- Produces: `PublicCard` (pydantic, `extra="forbid"`): `schema_version: Literal["feed.v1"]`, `id`, `type`, `source`, `title`, `url`, `channel`, `published_at` (the card's `consumed_at`), `topic: str` (primary), `format`, `key_points: list[{text, topic, t, confidence}]`, `relevance_score: int | None`, `provenance: {transcript, model}`; deliberately absent: `tier`, `user` signals, sub-scores, `action`, secondary topics of private origin. `set_visibility(store: Store, card_id: str, visibility: Literal["private","publishable"]) -> None` (explicit, one card); `export_feed(store: Store, out_path: Path) -> int` (only `visibility == "publishable"`, sorted by `published_at` then id, one JSON object per line, atomic, byte-identical on repeat); `export_feed_schema(path: Path) -> None`.

- [ ] **Step 1: Failing tests:** `test_private_cards_never_appear` (Review Focus 2); `test_only_whitelisted_fields_are_present` (the JSON keys equal the `PublicCard` field set exactly; markers placed in `user`, `tier`, `action` and sub-scores are absent); `test_publish_and_unpublish_roundtrip_and_unknown_id_raises_key_error`; `test_export_is_deterministic_and_atomic` (monkeypatched `os.replace` failure keeps the old file); `test_corrupt_card_files_are_skipped_not_exported`; `test_empty_feed_writes_an_empty_file`; `test_feed_schema_file_matches_model`; `test_cli_parser_has_publish_unpublish_export_feed`; `test_every_exported_line_has_provenance_and_validates_against_publiccard`.
- [ ] **Step 2-4:** FAIL, implement, PASS. **Step 5: Checkpoint.** Review Focus 2 is the reason this task gets an independent review at the end.

### Task 13: Chat export parsers and secret redaction

**Files:**
- Create: `src/secondbrain/chats.py` (parsers and redaction)
- Test: `tests/test_chat_parsers.py`, `tests/fixtures/chatgpt-conversations.json`, `tests/fixtures/claude-conversations.json`

**Interfaces:**
- Produces: `ChatMessage(msg_id: str, ts: datetime, text: str)`; `ChatConversation(source: Literal["chatgpt","claude"], conv_id: str, title: str, started_at: datetime, messages: list[ChatMessage])` (user side only); `parse_chatgpt(path: Path) -> list[ChatConversation]`; `parse_claude(path: Path) -> list[ChatConversation]`; `redact_secrets(text: str) -> str` replacing with `[REDACTED]`: `sk-[A-Za-z0-9_-]{20,}`, `AKIA[0-9A-Z]{16}`, `gh[pousr]_[A-Za-z0-9]{36,}`, `xox[baprs]-[A-Za-z0-9-]{10,}`, `AIza[0-9A-Za-z_-]{35}`, `\d{8,10}:[A-Za-z0-9_-]{35}` (Telegram tokens), `Bearer\s+[A-Za-z0-9._~+/=-]{20,}`, JWTs (`eyJ...` three dot-separated parts), PEM private key blocks, and the password part of `scheme://user:password@host` URLs.
- Parsers keep only messages by the user (ChatGPT `author.role == "user"`, Claude `sender == "human"`), text content only, sorted by timestamp, with redaction applied at parse time.

- [ ] **Step 1 (user action, before writing fixtures):** ask him for a small real export of each service (a few conversations) and base the fixtures on the real structure, not on assumptions. Gemini is added later from a real Takeout sample.
- [ ] **Step 2: Failing tests:** `test_chatgpt_parser_keeps_only_user_messages_in_time_order`; `test_claude_parser_keeps_only_human_messages`; `test_non_text_parts_and_empty_messages_are_skipped`; `test_malformed_file_raises_value_error_with_path` and `test_non_list_json_raises_value_error`; `test_missing_ids_or_timestamps_are_skipped_not_fatal`; one parametrised `test_redaction_<pattern>` per pattern above with realistic-looking fake secrets; `test_redaction_keeps_normal_text_and_is_idempotent`; `test_parsers_redact_before_returning`; `test_unicode_text_preserved`; `test_huge_message_is_truncated_to_20000_chars`.
- [ ] **Step 3-5:** Run FAIL, implement, run PASS (whole suite). Checkpoint.

### Task 14: Chat ingestion

**Files:**
- Modify: `src/secondbrain/chats.py`, `src/secondbrain/cli.py` (`sb ingest-chats --source chatgpt|claude --file PATH [--limit N]`)
- Test: `tests/test_chat_ingest.py`

**Interfaces:**
- Produces: `class ChatDigest(BaseModel)`: `topic: str`, `key_points: list[str]` (max 7), `decisions: list[str]` (max 5), `open_questions: list[str]` (max 5); `conversation_card_id(source: str, conv_id: str) -> str` = `ai_<source>_<conv_id with every character outside [A-Za-z0-9_-] replaced by "_", truncated to 60>`; `ingest_chats(convs: Sequence[ChatConversation], store: Store, router: Router, limit: int | None = None) -> ChatIngestReport(new_cards: int, skipped_existing: int, skipped_short: int, failures: list[tuple[str, str]])`.
- Behaviour: skip conversations whose total user text is under 80 chars; skip ids already in the store; user text is limited to the first 12 000 chars; the digest comes from `router.route("triage", "private")` (local only); the card is `type="thought"`, `source` = the chat service, `visibility="private"`, topic via `validate_topic`, key points = digest key points plus decisions prefixed `Decision: `, open questions prefixed `Open: `, `consumed_at` = conversation start, `provenance.model` = provider name. Per-item `LLMOutputError`/`ProviderError` -> `failures`, the loop continues.

- [ ] **Step 1: Failing tests:** `test_assistant_text_never_reaches_the_prompt_or_the_card`; `test_secrets_never_reach_the_prompt_or_the_card` (Review Focus 4); `test_short_conversations_skipped`; `test_reimport_is_idempotent_and_makes_no_llm_call`; `test_card_id_sanitised_and_valid_for_the_store`; `test_cloud_route_raises_sensitivity_error_and_nothing_is_written` (Review Focus 3); `test_one_bad_digest_does_not_stop_the_run`; `test_limit_respected`; `test_long_conversation_prompt_is_bounded_to_12000_chars`; `test_cards_are_private_thought_type`; `test_cli_parser_ingest_chats_arguments`.
- [ ] **Step 2-4:** FAIL, implement, PASS. **Step 5 (acceptance, manual, after Task 13 step 1):** ingest his sample exports with the local model and spot-check that no secret and no assistant text appears in the cards. **Step 6: Checkpoint.**

### Task 15: Retrieval evaluation set

**Files:**
- Create: `src/secondbrain/evals.py`, `docs/evals/questions.json` (starter file with the format and one example)
- Modify: `src/secondbrain/cli.py` (`sb eval`), `src/secondbrain/bot/brief.py` (one retrieval line in the weekly review)
- Test: `tests/test_evals.py`

**Interfaces:**
- Produces: `EvalQuestion(id: str, question: str, expect_ids: list[str])` (a hit is any expected id in the top k); `load_questions(path: Path) -> list[EvalQuestion]` (corrupt file -> `ValueError` naming the path); `@dataclass EvalResult(hit_rate: float, mrr: float, per_question: list[tuple[str, int | None]])` (rank of the first expected id, None if missing); `run_eval(index: Index, questions: list[EvalQuestion], k: int = 5) -> EvalResult`; `record_and_compare(history_path: Path, result: EvalResult, now: datetime) -> float | None` (appends to `raw/eval_history.jsonl`, returns the change in hit_rate against the previous run, None for the first run); `REGRESSION_DROP = 0.10`.
- `sb eval` prints hit rate, MRR, failing questions and a regression warning when the drop is at least 0.10. The weekly review shows the latest hit rate.

- [ ] **Step 1: Failing tests (HashEmbedder, tmp store):** `test_perfect_retrieval_gives_hit_rate_one_and_mrr_one`; `test_missing_expected_id_counts_as_miss_and_rank_none`; `test_mrr_for_second_rank_is_half`; `test_empty_question_list_returns_zero_without_error`; `test_history_records_and_reports_drop_and_first_run_is_none`; `test_regression_flag_at_ten_point_drop`; `test_corrupt_questions_file_raises_value_error_with_path`; `test_weekly_review_includes_retrieval_line_when_available`.
- [ ] **Step 2-4:** FAIL, implement, PASS. **Step 5 (user action, after the first ingest):** he writes about 15 real questions with expected card ids in `docs/evals/questions.json`; run `sb eval` and record the baseline in `docs/experiments/eval-baseline.md`. **Step 6: Checkpoint.**

### Task 16: Wiring, documentation and acceptance

**Files:**
- Modify: `src/secondbrain/cli.py` (`sb lifecycle [--dry-run]`, `sb week [--week W]` printing the review text locally), `docs/RUNBOOK.md`, `docs/NEXT_STEPS.md`, `docs/PROJECT_STATE.md`, `docs/decisions.md`
- Test: `tests/test_cli_stage3.py`

- [ ] **Step 1: Failing tests:** `test_lifecycle_dry_run_changes_nothing_and_prints_plan`; `test_lifecycle_command_demotes_and_prints_report`; `test_week_command_prints_review_without_sending_anything`; `test_parser_has_all_stage3_5_commands` (`lifecycle`, `week`, `week-packet`, `import-theme`, `publish`, `unpublish`, `export-feed`, `ingest-chats`, `eval`).
- [ ] **Step 2-4:** FAIL, implement, PASS. **Step 5:** run the entire suite with `-m slow` once. **Step 6 (manual acceptance):** with real data, run `sb lifecycle --dry-run`, read one `sb week` output, confirm the first Sunday review arrives in Telegram, publish one card and open `feed/publishable.jsonl` to check it contains only public fields. **Step 7:** update the runbook, NEXT_STEPS and decisions docs for the new commands. **Step 8: Checkpoint** and ask him about git.

---

## Deferred on purpose (with triggers)

- **cognee:** only if `sb eval` hit rate stays below 0.6 after tuning, or multi-hop questions fail. Cards stay the source of truth, so adding it means indexing.
- **sqlite-vec / ANN index (stage S2):** when search latency exceeds 2 s or cards exceed 10 000.
- **Automatic YouTube history (yt-dlp with cookies):** after 2-3 weeks of Takeout use. Google Takeout can schedule recurring exports, which may be enough.
- **Gemini chat import:** needs a real Takeout sample from him first.
- **Opportunity finder:** its own brainstorm and plan once he has 1-2 months of friction and experiment data.
- **Re-digesting a chat that grew after import:** the card id exists, so it is skipped; revisit if it matters.

## Self-Review notes

- Spec coverage: lifecycle, tombstone demotion, raw purge (Tasks 1-2); usage and cost line (3); weekly metrics including consumed-versus-produced, say-do, goal-linked share, entertainment, surprises with rescue, adapter-free health via usage (4, 7); themes and consolidation, Claude-assisted weekly synthesis (5, 6); resurfacing (8); experiment and friction workflows (9, with metrics in 4); belief audit, profile never overwritten, contradiction/challenge mode (10, 11); consumers contract feed (12); AI chats (13, 14); evaluation set and regression test (15); cognee and S2 triggers (Deferred). The weekly "contradictions between creators" line is not implemented: it needs the beliefs and themes to exist first; revisit after a month of data.
- Entertainment "hours" from the design cannot be computed (Takeout has no watch duration), so the plan counts videos instead.
- Type consistency: `Store.demote_to_tombstone`, `Theme`, `Belief`, `WeekMetrics`, `Brief`, `UsageSummary`, `ChatConversation` are each defined once and used by the same names later; `run_due_jobs` changes shape in Task 7 and every later job uses the builders form.
- Proportion: the plan is a set of signatures, test names with exact values and constraints, not a transcript of the code.
