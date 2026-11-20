# Retrieval and Memory v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/ask` answer from the right evidence at any scale and at low Claude cost: paragraph-level search, a living local memory (digests + profile), exact counting, a deliberate `/deep` mode, and a retrieval test set to prove it.

**Architecture:** Everything expensive (summaries, tagging, re-ranking, counting) runs on the free local model or in plain code, incrementally (cost grows with NEW notes, never with total notes). Claude only receives a small, dense, honest pack. Digests are stored as ordinary cards (`source="digest"`), so search, privacy filtering, backup and the data-repo sync work unchanged.

**Tech Stack:** Python 3.12, sqlite3 (FTS5, WAL), numpy (float16 matrix cache), existing Ollama models (`qwen2.5:7b`, `nomic-embed-text`), python-telegram-bot, pytest. **No new dependencies.**

**Spec:** the 5-point proposal agreed in chat on 2026-11-20 (summary in "Scale and efficiency review" below), plus `docs/design.md` sections 5-8 and `docs/decisions.md`. Supersedes Task 5 (themes) and Task 15 (evals) of `2026-11-17-second-brain-stage-3-5.md`.

## Global Constraints

- Python 3.12, Windows 11, one laptop, zero cost, no new paid service and no new dependency without his approval.
- Never modify or depend on SkipATS. No `git add/commit/push` in the CODE repo without his explicit approval each time (auto-push of the separate data repo by the sync job is already approved).
- Private data: cards with `channel == "local-only"` (entries saved with `/private`) never enter any Claude pack, digest, tag count, theme or profile. Digests, tags, expansions, re-ranking and `/deep` condensing use the LOCAL model only. Claude only sees: the `/ask` pack (bounded), the `/deep` condensed digest (bounded), the mentor flows already approved.
- `profile/profile.md` is HIS hand-written file (restored 2026-11-20 after the mentor overwrote it; the mentor now writes `profile/onboarding.md`). No generated job may write it. Generated profile files are separate.
- Every file write atomic (temp + `os.replace`); every job safe to re-run; a failed generation leaves the previous file untouched.
- Claude budgets (hard caps, in code): `/ask` pack <= 9000 chars; `/deep` digest <= 9000 chars and <= 3 per day; no Claude call anywhere in this plan except those two.
- Card ids, `schema.py` taxonomy and `card.v1` stay backward compatible (new Card fields are optional).

## Scale and efficiency review (findings that shaped this plan)

| Finding in today's code | Why it matters at scale | Decision |
|---|---|---|
| Search shows only a card's FIRST key point; long journals and `/book` logs lose paragraphs 2+ | answers miss the evidence even when the card matched | chunk-level index (Task 2) |
| Embedding input is cut at 4000 chars | a long voice ramble is only partly searchable | one embedding per chunk, chunk <= 900 chars (Task 2) |
| Every query reads ALL vectors from SQLite and rebuilds the matrix | 50k chunks = 150 MB read per question | in-process float16 matrix cache, refreshed by a version counter (Task 2) |
| Every sync parses EVERY card file | O(total notes) each 2 h | manifest of (mtime, size); parse only changed files (Task 2) |
| Index lags up to 2 h after a save | a note from 10 min ago is not matched | index the saved card immediately (Task 3) |
| Profile cut to 1800 of 3277 chars in the pack | Claude sees half the profile | pack budget 2500 chars (Task 3) |
| `profile/profile.md` was overwritten by the mentor at 14:01 (hand-written version recovered from the data repo history) | violates "never overwrite hand-written" | FIXED before this plan: mentor writes `profile/onboarding.md`, test added; living profile goes to `profile/living.md` (Task 4) |
| Session summaries (`cc_`) are deliberately kept out of Claude packs | a digest built from "all cards" would leak them | digests only use the pack sources (Task 4) |
| The bot (`add_card`) and the scheduled sync (`update`) are two PROCESSES on one SQLite file | `os.replace` of a DB that another process has open fails on Windows; swapping under a live WAL corrupts | rebuild into staging tables inside the same file and swap by rename in one transaction; two-process test (Task 2) |
| Eval questions made from private notes would land in the code repo | private text committed | store at `profile/evals/questions.json` (data repo), only a format example in `docs/` (Task 1) |

**Scale targets** (design for 1M chunks, comfortable at 300k; realistic volume is about 50k chunks per year): warm query <= 300 ms at 200k chunks (one matmul on a 200k x 768 float16 matrix, about 300 MB); sync with 20k unchanged cards <= 5 s (stats only); local LLM work per sync capped at 6 calls (about 30 s). **Deferred with triggers:** hnswlib approximate index when chunks > 300k or p95 query > 400 ms; cross-encoder re-ranker if the eval shows ranking (not recall) is the weak point.

**Honest limits:** tags come from a 7B model, so counts are labelled approximate and show tagged coverage; digests are lossy, so raw cards stay the source of truth and digests cite card ids; coverage line tells Claude (and him) how much evidence a pack really holds.

## Build order (recommended)

- **Phase A, now:** Tasks 1-3 (measure, paragraph-level search, honest pack, instant indexing). Biggest quality gain, no new background jobs, small risk surface.
- **Phase B, next session:** Task 4 (digests, living profile), once Phase A is verified and committed.
- **Phase C, after a few weeks of real notes:** Tasks 5-6 (counting, `/deep`) and the Task 7 acceptance for them. Reason: 37 cards cannot show whether counting or `/deep` is needed; the eval and his real questions decide.
- **Prerequisite for Task 2:** the current uncommitted work (voice, inbox/outbox, `/thought`, netfix, profile fix, docs) is committed first, with his approval, so the index rewrite has a rollback point.

## Review Focus

1. **Private text in a pack, digest, tag count or eval file:** `local-only` card reaching Claude, a digest, a count, or the committed repo. Expected: excluded everywhere; eval questions stored in the data repo path. (Tasks 1, 3, 4, 5)
2. **Index corruption under concurrency:** the bot indexing a new card while sync updates or rebuilds; crash mid-update; schema upgrade. Expected: WAL + transactions, atomic rebuild, old index kept on failure, search never sees half-built data. (Task 2)
3. **Memory overwritten or invented:** a failed or hallucinating generation replacing a good digest/profile; cited card ids that do not exist; `profile.md` touched. Expected: previous file kept, unknown ids dropped, hand-written files never written. (Task 4)
4. **A count presented as exact:** wrong tag, untagged notes, ambiguous question. Expected: approximate label with tagged/total, no count path when no single tag matches. (Task 5)
5. **Runaway cost or latency:** expansion on every question, `/deep` loops, huge note (50k chars), empty or emoji-only note. Expected: expansion only when the top score is weak and at most once; at most 6 local calls per `/deep`; chunking bounds all inputs; empty note yields no chunks. (Tasks 2, 3, 6)

## File Structure

```
src/secondbrain/
  evals.py        (new)   eval questions, recall/MRR, synthetic question suggestion
  chunks.py       (new)   Card -> Chunk list (paragraph-level search units)
  index.py        (mod)   chunk tables, matrix cache, manifest, add_card, local_only filter
  store.py        (mod)   iter_card_files, read_card_file
  retrieval.py    (new)   retrieve (RRF, adaptive expansion), coverage line, evidence formatting
  digest.py       (new)   day/week/month digest cards, living profile, refresh
  tags.py         (new)   tag vocabulary, TagStore sidecar, tagging, count questions
  deep.py         (new)   wide retrieval + local condensing for /deep
  advisor.py      (mod)   pack built from retrieval + counts + coverage + evidence rule
  schema.py       (mod)   Card.derived_from (optional)
  config.py       (mod)   living_profile_path, onboarding_profile_path, tags_path, evals_path
  mentor/flow.py  (mod)   ask(extra_context); profile text prefers living.md
  bot/app.py      (mod)   instant indexing, /deep, prompt box
  cli.py          (mod)   sb eval | digest | tags | index --stats, sync steps
tests/ one test file per new module, plus additions to test_index.py, test_advisor.py, test_bot_app.py
profile/evals/questions.json, profile/living.md, profile/onboarding.md, profile/tags.txt (generated or his, all data)
```

---

### Task 1: Retrieval evaluation (baseline before any change)

**Files:**
- Create: `src/secondbrain/evals.py`, `docs/evals/questions.example.json`
- Modify: `src/secondbrain/cli.py` (`sb eval`, `sb eval --suggest N`), `src/secondbrain/config.py` (`evals_path = root/"profile"/"evals"/"questions.json"`)
- Test: `tests/test_evals.py`

**Interfaces:**
- Consumes: `Store.iter_cards`, `Index.search`, `llm.complete_json`, local `Provider`.
- Produces: `EvalQuestion(id: str, question: str, expect_ids: list[str])` (pydantic, extra forbid); `load_questions(path: Path) -> list[EvalQuestion]` (corrupt file -> `ValueError` naming the path; missing file -> `[]`); `@dataclass(frozen=True) EvalResult(recall_at_5: float, recall_at_10: float, mrr: float, misses: list[str])`; `run_eval(questions: list[EvalQuestion], search: Callable[[str, int], list[str]]) -> EvalResult` (`search(question, k)` returns CARD ids in rank order, de-duplicated); `suggest_questions(store: Store, llm: Provider, n: int, seed: int = 0) -> list[EvalQuestion]` (samples non-local-only, non-digest cards with >= 40 chars of text; one model call per card asking for a question this note answers WITHOUT reusing the note's own key words; failures dropped; deterministic for a seed). **Caveat, printed by `sb eval --suggest`:** generated questions are a smoke test only (small library, model-written questions); real quality needs about 5 questions he writes himself later.

- [ ] **Step 1: Failing tests** (HashEmbedder, tmp store, fake llm): `test_perfect_search_gives_recall_one_and_mrr_one`; `test_missing_expected_id_is_a_miss_listed_in_misses`; `test_mrr_for_second_rank_is_half`; `test_empty_question_list_returns_zeros_without_error`; `test_corrupt_questions_file_raises_valueerror_naming_the_path`; `test_suggest_skips_local_only_and_digest_cards` (Review Focus 1); `test_suggest_is_deterministic_for_a_seed_and_drops_llm_failures`.
- [ ] **Step 2: Run, expect FAIL.** `.venv\Scripts\python -m pytest tests/test_evals.py -q`
- [ ] **Step 3: Implement** `evals.py`; `sb eval` loads `settings.evals_path`, builds `search` from `Index.search` mapped to card ids, prints recall@5, recall@10, MRR and misses; `sb eval --suggest N` writes suggested questions (merging, never overwriting existing ids) and prints that they are drafts to review.
- [ ] **Step 4: Run tests, expect PASS.**
- [ ] **Step 5: Baseline (user-visible):** run `sb eval --suggest 25` then `sb eval`; record the baseline numbers in `docs/experiments/retrieval-v2.md` (numbers only, no note text), labelled "smoke test, 37 cards".

### Task 2: Chunk-level index, matrix cache, incremental scan

**Files:**
- Create: `src/secondbrain/chunks.py`; Test: `tests/test_chunks.py`
- Modify: `src/secondbrain/index.py`, `src/secondbrain/store.py`, `tests/test_index.py`

**Interfaces:**
- Produces (chunks): `CHUNK_MAX_CHARS = 900`; `@dataclass(frozen=True) Chunk(id: str, card_id: str, ord: int, text: str)` with id `f"{card_id}#{ord}"`; `chunk_card(card: Card) -> list[Chunk]` (one chunk per key point and one for the action text; a key point longer than 900 chars is split at sentence boundaries, hard-split if no boundary; `card.reply_to` is prefixed to chunk 0 as `(in reply to: ...)`; no text -> `[]`).
- Produces (store): `Store.iter_card_files() -> Iterator[Path]`; `Store.read_card_file(path: Path) -> Card`.
- Produces (index): `Hit` gains `date: str = ""` (ISO date of the card) and `source: str = ""`; `snippet` is now the matching CHUNK text. `Index.search(query: str, k: int = 5, per_source_cap: int = 3, per_card_cap: int = 2, include_local_only: bool = True) -> list[Hit]`; `Index.related(text, k=3, min_cosine=0.55, exclude=frozenset(), include_local_only=True)` returns at most ONE hit per card, and `exclude` holds CARD ids (not chunk ids), so a just-saved note can never suggest itself; `Index.update(store) -> tuple[int, int, int]` still returns (cards added or changed, cards removed, cards total); `Index.add_card(card: Card) -> None`; `Index.chunk_count() -> int`. Schema version 2 stored in `meta('schema')`; any other version triggers a full rebuild INTO STAGING TABLES inside the same database file (`chunks_new`, `fts_new`), swapped in by renaming in ONE transaction. The database file is never replaced with `os.replace` (the bot process may have it open). Tables: `chunks(id PK, card_id, ord, text, date, source, importance, local_only, vec BLOB, sig)`, FTS5 over chunk text, `manifest(path PK, mtime_ns, size, card_id)`. Connections use `PRAGMA journal_mode=WAL; busy_timeout=5000`. The matrix cache keeps L2-normalised float16 vectors; `add_card` APPENDS rows to the cache (no full reload per message); a full reload happens only when rows were removed or changed (`meta('version')` for removals and updates, `meta('appended')` for appends).

- [ ] **Step 1: Failing tests:** `test_short_note_is_one_chunk`; `test_long_key_point_splits_at_sentences_under_900_chars`; `test_reply_context_is_part_of_chunk_zero`; `test_empty_card_has_no_chunks`; `test_fifty_thousand_char_note_is_bounded_and_does_not_crash` (Review Focus 5); `test_search_finds_a_later_paragraph_of_a_long_journal` (the regression: card with 4 paragraphs, query about paragraph 4, hit snippet contains paragraph 4); `test_search_never_returns_local_only_when_excluded` (Review Focus 1); `test_update_parses_only_changed_files` (count calls to `read_card_file` on a second `update`: 0 for unchanged, 1 for one edit); `test_add_card_makes_a_note_searchable_without_update`; `test_second_index_instance_sees_add_card_via_version_counter`; `test_old_schema_index_is_rebuilt_atomically_and_old_file_kept_on_failure` (Review Focus 2); `test_two_processes_add_card_and_update_and_rebuild_do_not_corrupt` (uses `multiprocessing`: one process loops `add_card`, another runs `update` and a forced schema rebuild; afterwards `PRAGMA integrity_check` is `ok` and every card id is searchable); `test_related_returns_one_hit_per_card_and_excludes_by_card_id`; `test_add_card_does_not_reload_the_whole_matrix`. Slow test (marker `slow`, run once by hand): `test_two_hundred_thousand_chunks_query_under_300ms_warm`.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** `chunks.py`; extend `store.py`; rewrite `index.py` internals keeping the public names above. Approach: FTS5 gives bm25 candidates, the cache gives cosine for all chunks in one `matrix @ q`, blend as today (`0.5*bm + 0.5*cos` times importance weight, stopwords kept out of the FTS query), then apply `per_card_cap` and `per_source_cap`.
- [ ] **Step 4: Run full test suite, expect all PASS** (existing 404 tests keep passing; adapt fixtures only where `Hit` fields changed).
- [ ] **Step 5: Run the slow perf test once and record the timing in `docs/experiments/retrieval-v2.md`; re-run `sb eval`, record recall.**
- [ ] **Step 6: Checkpoint:** record in `docs/ledger.md`; no commit without his approval.

### Task 3: Retrieval v2, honest pack, instant indexing

**Files:**
- Create: `src/secondbrain/retrieval.py`; Test: `tests/test_retrieval.py`
- Modify: `src/secondbrain/advisor.py` (`build_context`, `_index_matches`), `src/secondbrain/bot/app.py` (`_index_soon`), `tests/test_advisor.py`, `tests/test_bot_app.py`

**Interfaces:**
- Consumes: `Index.search(..., include_local_only=False)`, `llm.complete_json`.
- Produces: `@dataclass(frozen=True) Evidence(card_id: str, date: str, source: str, text: str, score: float)`; `@dataclass(frozen=True) Retrieval(items: list[Evidence], weak: bool, expansions: list[str])`; `retrieve(index: Index, question: str, *, k: int = 8, expand: Callable[[str], list[str]] | None = None, weak_below: float = 0.5, exclude: frozenset[str] = frozenset(), sources: frozenset[str] | None = None) -> Retrieval` (searches k*3 candidates for the question; only when the best score is below `weak_below` and `expand` is given, calls `expand` ONCE and fuses all rankings with reciprocal-rank fusion; returns top k); `rrf(rankings: list[list[str]], k: int = 60) -> list[str]`; `make_expander(llm: Provider) -> Callable[[str], list[str]]` (<= 3 rephrasings, any failure -> `[]`); `format_evidence(items: list[Evidence]) -> list[str]` lines `"[2026-11-18 journal tg_12] text"`; `coverage_line(items: list[Evidence]) -> str` e.g. `"Evidence: 6 notes from 2026-10-03 to 2026-11-18 (journal 4, advice 2)."` (empty items -> `"Evidence: none found."`). `EVIDENCE_RULE` constant added to the `/ask` prompt: say what the evidence does not cover instead of guessing. `PROFILE_PACK_CHARS = 2500` (was 1800).

- [ ] **Step 1: Failing tests:** `test_strong_match_does_not_call_expand`; `test_weak_match_calls_expand_once_and_fuses`; `test_expand_failure_falls_back_to_plain_results`; `test_local_only_card_never_appears_in_evidence` (Review Focus 1); `test_rrf_orders_by_combined_rank`; `test_coverage_line_format_and_empty_case`; `test_pack_total_size_stays_under_the_budget`; `test_profile_is_included_up_to_2500_chars`; `test_new_note_is_retrievable_immediately_via_index_soon` (bot saves a note, `add_card` runs, `retrieve` finds it with no sync).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** `retrieval.py`; in `advisor.build_context` replace `_index_matches` with `retrieve` (keep the keyword fallback when the index is missing), add the coverage line under the evidence block and `EVIDENCE_RULE` to the prompt; in `bot/app.py` add `_index_soon(d, card)` that runs `index.add_card` in `asyncio.to_thread` as a tracked background task after a note is saved (called for every saved note including quiet `/thought` saves; failure is only logged).
- [ ] **Step 4: Run all tests, expect PASS.**
- [ ] **Step 5: Re-run `sb eval`; record recall before/after in `docs/experiments/retrieval-v2.md`.**

### Task 4: Digests and the living profile (local, incremental)

**Files:**
- Create: `src/secondbrain/digest.py`; Test: `tests/test_digest.py`
- Modify: `src/secondbrain/schema.py` (`Card.derived_from: list[str] = Field(default_factory=list, max_length=60)`, regenerate `schemas/card.v1.json`), `src/secondbrain/config.py` (`living_profile_path`, `onboarding_profile_path`), `src/secondbrain/mentor/flow.py` (`_profile_text` prefers `living.md` once it exists, else hand-written `profile.md` + `onboarding.md`; the onboarding write fix is already done), `src/secondbrain/advisor.py` (`CONTEXT_SOURCES` gains `"digest"`; profile source order as above), `src/secondbrain/cli.py` (`sb digest`; sync step), `tests/test_mentor.py`

**Interfaces:**
- Consumes: `Store`, `Index`, local `Provider`, `complete_json`.
- Produces: `build_day_digest(store: Store, day: date, llm: Provider, now: datetime) -> Card | None` (card id `dgd_YYYYMMDD`, `source="digest"`, `type="thought"`, `consumed_at` = that day at 23:59 local so month folders stay stable, `key_points` <= 6 bullet facts, `derived_from` = ids of the cards used: ONLY cards from the pack sources (`advisor.CONTEXT_SOURCES` minus the ledger types), never `local-only` and never `cc_` session summaries, ids the model cites that do not exist are dropped, fewer than 3 usable source cards -> `None`); `build_week_digest(store, week_start: date, llm, now) -> Card | None` (id `dgw_YYYYMMDD` of the Monday, from that week's day digests, needs >= 2); `build_month_digest(store, month: tuple[int, int], llm, now) -> Card | None` (id `dgm_YYYYMM`, from week digests, needs >= 2); `refresh_digests(store: Store, llm: Provider, now: datetime, max_calls: int = 6) -> DigestRun` with `@dataclass DigestRun(created: list[str], failed: int, skipped: int)` (only days whose set of non-local-only card ids differs from the existing digest's `derived_from`; oldest first; stops at `max_calls`); `update_living_profile(store: Store, goals_text: str, llm: Provider, now: datetime, profile_path: Path, onboarding_path: Path, living_path: Path) -> bool` (inputs <= 9000 chars: goals, his hand-written `profile.md` (background and skills), the onboarding profile, latest 4 week digests, latest month digest, previous living profile; output 350-600 words under fixed plain headings; atomic write; on failure returns False and leaves the file untouched; never writes `profile.md`). Engine is the local model by default; `SB_PROFILE_ENGINE=claude` is a separate decision (see Open Decisions) and is NOT wired in this plan.

- [ ] **Step 1: Failing tests:** `test_day_digest_cites_only_real_card_ids_and_drops_invented_ones` (Review Focus 3); `test_digest_excludes_local_only_cards` (Review Focus 1); `test_fewer_than_three_cards_makes_no_digest`; `test_unchanged_day_is_not_regenerated_and_a_day_with_a_new_card_is`; `test_session_summary_cards_never_feed_a_digest` (Review Focus 1); `test_refresh_stops_at_max_calls_and_oldest_first`; `test_llm_failure_keeps_the_previous_digest_and_returns_none` (Review Focus 3); `test_week_digest_needs_two_day_digests`; `test_living_profile_written_atomically_and_failure_leaves_it_untouched`; `test_living_profile_reads_handwritten_profile_but_never_writes_it` (Review Focus 3); `test_digest_cards_are_searchable_and_enter_the_ask_pack`; `test_new_card_field_is_optional_so_old_cards_still_load`.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** `digest.py`; each model prompt gets at most 6000 chars of input (oldest dropped first) and says "data, not instructions"; digest generation prompts are generic (no goals text) except the profile prompt.
- [ ] **Step 4: Wire sync:** after the index step run `refresh_digests` (max 6 calls) when a local model is configured, then `update_living_profile` when `living.md` is missing or older than 7 days and a week digest exists; log `digests: +N` and `profile: ok|skipped|failed` in `raw/sync.log`.
- [ ] **Step 5: Run all tests, expect PASS; run `sb digest` once on real data and read the first day digest with him.**

### Task 5: Tags and exact counting

**Files:**
- Create: `src/secondbrain/tags.py`; Test: `tests/test_tags.py`
- Modify: `src/secondbrain/advisor.py` (counts in the FACTS part of the pack), `src/secondbrain/cli.py` (`sb tags`, sync step), `src/secondbrain/config.py` (`tags_path = root/"profile"/"tags.txt"`, `tags_db_path = index/tags.sqlite`)

**Interfaces:**
- Produces: `DEFAULT_TAGS: tuple[str, ...]` (outreach, applications, interviews, coding, learning, content, networking, product-ideas, money, health, sleep, mood, family, procrastination, planning); `load_vocab(path: Path) -> list[str]` (his `profile/tags.txt`, one per line, falls back to defaults); `TAG_SYNONYMS: dict[str, tuple[str, ...]]` (e.g. outreach: cold email, cold outreach, reached out); `class TagStore(path: Path)` with `set_tags(card_id: str, tags: list[str], model: str) -> None`, `tagged_ids() -> set[str]`, `count(tag: str, store: Store, since: datetime, until: datetime) -> CountResult`; `@dataclass(frozen=True) CountResult(n: int, ids: list[str], tagged: int, total: int)` (total = non-local-only note cards in the period); `tag_new_cards(store: Store, tag_store: TagStore, llm: Provider, vocab: list[str], max_calls: int = 5, batch: int = 8) -> int` (untagged non-local-only, non-digest cards, <= 600 chars each; tags outside the vocabulary are dropped; a card with no valid tag is stored as `[]` so it is not retried); `@dataclass(frozen=True) CountQuery(tag: str, since: datetime, until: datetime, label: str)`; `parse_count_question(question: str, vocab: list[str], now: datetime) -> CountQuery | None` (needs a count phrase such as "how many", "how often", "number of times", exactly one vocabulary tag or synonym; periods: today, this week, last week, this month, last 30 days (default)); `counts_fact(result: CountResult, query: CountQuery) -> str` -> `"COUNT (approximate, tags assigned by a local model): outreach in the last 30 days = 4 notes (17 of 19 notes in that period were tagged). Ids: tg_3, tg_9, ..."`.

- [ ] **Step 1: Failing tests:** `test_tags_outside_the_vocabulary_are_dropped`; `test_untaggable_card_is_stored_empty_and_not_retried`; `test_local_only_and_digest_cards_are_never_tagged` (Review Focus 1); `test_batching_uses_one_call_per_eight_cards_and_respects_max_calls`; `test_parse_count_question_period_and_tag`; `test_question_with_two_tags_or_no_tag_or_no_count_phrase_returns_none` (Review Focus 4); `test_counts_fact_states_approximate_and_tagged_coverage` (Review Focus 4); `test_count_ignores_cards_outside_the_period`; `test_ask_pack_contains_the_count_fact_for_a_count_question_and_not_otherwise`.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** `tags.py`; `advisor.build_context` adds the count fact when `parse_count_question` matches (tag store opened read-only; missing store -> no fact); sync step `tag_new_cards` after digests (max 5 calls).
- [ ] **Step 4: Run all tests, expect PASS.**

### Task 6: `/deep` mode

**Files:**
- Create: `src/secondbrain/deep.py`; Test: `tests/test_deep.py`
- Modify: `src/secondbrain/mentor/flow.py` (`Mentor.ask(..., extra_context: str = "")` forwards it as `advisor_ask(extra=...)`), `src/secondbrain/bot/app.py` (`/deep`, `PROMPTS["deep"]`, `MENU_COMMANDS`, `HELP_TEXT`, `DEEP_DAILY_LIMIT = 3`), `tests/test_bot_app.py`

**Interfaces:**
- Produces: `@dataclass(frozen=True) DeepDigest(text: str, notes: int, date_from: str, date_to: str, local_calls: int, truncated: bool)`; `build_deep_digest(index: Index, store: Store, question: str, llm: Provider | None, now: datetime, *, wide_k: int = 60, max_local_calls: int = 6, out_chars: int = 9000) -> DeepDigest` (retrieves `wide_k` chunks with `include_local_only=False`, groups by date, batches of <= 10 chunks, one local call per batch to extract only facts relevant to the question with dates, joins, trims the oldest facts above `out_chars`; first line is the coverage line; `llm is None` or any local failure -> falls back to the top 24 raw evidence lines, never raises); `deep_used_today(state: dict, now: datetime) -> int` and `bump_deep(state: dict, now: datetime) -> dict` (counter keyed by local date inside `bot_state.json`).

- [ ] **Step 1: Failing tests:** `test_deep_digest_uses_at_most_max_local_calls` (Review Focus 5); `test_deep_digest_never_exceeds_out_chars_and_marks_truncated`; `test_deep_excludes_local_only_cards` (Review Focus 1); `test_local_model_down_falls_back_to_raw_evidence_without_raising`; `test_deep_command_refuses_the_fourth_use_of_the_day_politely`; `test_bare_deep_opens_the_reply_box_and_reply_runs_deep`; `test_deep_answer_goes_through_the_outbox_when_sending_fails`; `test_deep_reply_is_never_replayed_after_a_crash` (like `/ask`).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** `deep.py` and the command (progress message "Searching deeper, about a minute..."); the question plus digest go to Claude through `Mentor.ask`, so the persona, guards, usage section `ask` and exchange saving stay the same; usage section label `deep` for the local condensing calls.
- [ ] **Step 4: Run all tests, expect PASS.**

### Task 7: Wiring, scale acceptance, documentation

**Files:**
- Modify: `src/secondbrain/cli.py` (`sb index --stats`: chunks, cache size, last update), `docs/decisions.md`, `docs/RUNBOOK.md`, `docs/NEXT_STEPS.md`, `scripts/sb-status.ps1` (digest/tag counts), `CLAUDE.md` wording only after his approval (daily mentor messages use Claude)
- Test: `tests/test_hardening.py` additions

- [ ] **Step 1: Failing tests:** `test_sync_log_line_reports_digests_tags_and_profile_status`; `test_sync_with_no_local_model_skips_digests_and_tags_without_failing`; `test_index_stats_command_prints_chunk_count`.
- [ ] **Step 2: Implement, run all tests, expect PASS.**
- [ ] **Step 3: Scale acceptance (record numbers in `docs/experiments/retrieval-v2.md`):** slow perf test (200k chunks, warm query <= 300 ms); an unchanged-library sync of 20k synthetic cards <= 5 s; peak memory of the bot with the cache loaded.
- [ ] **Step 4: Before/after:** `sb eval` recall@5, recall@10, MRR on the same questions, plus three real `/ask` questions he picks, answered before (git stash not needed: numbers from Task 1/3) and after.
- [ ] **Step 5: Update docs and `docs/decisions.md` (privacy rule for digests, `/deep` cap, profile files). Show him the full file list and a commit message; commit and push the code repo only with his explicit approval.**

## Open Decisions (his call, defaults chosen)

1. **Build order:** phased as above (recommended) or all seven tasks now. I earlier said counting and `/deep` should wait until the eval shows a need; I still think so, because the bot has just had a run of bugs and 37 cards cannot prove those features are needed.
2. **Living profile engine:** local model (default, free, private) vs. one Claude call per week (better writing, uses the approved "weekly review" path). Default: local. Switch later with one setting.
3. **Execution approach:** Native (recommended) vs. Subagent-driven.

## Deferred on purpose (with triggers)

- hnswlib approximate index: when chunks > 300k or p95 query > 400 ms.
- Cross-encoder re-ranker: only if the eval shows the right chunk is retrieved but ranked low.
- Topic theme cards and LLM-discovered tags: after a month of real tag data shows which tags he actually uses.

## Self-Review notes

- Spec coverage: point 1 (retrieval) Tasks 2-3; point 2 (living memory) Task 4; point 3 (counting) Task 5; point 4 (deep) Task 6; point 5 (eval) Task 1; scale and efficiency Tasks 2, 4, 5, 6, 7.
- Types checked across tasks: `Hit.date/source` (Task 2) used by `Evidence` (Task 3); `include_local_only` (Task 2) used by Tasks 3 and 6; `Card.derived_from` (Task 4) used only there; `Provider` and `complete_json` come from `llm.py`; `extra_context` (Task 6) maps to existing `advisor.ask(extra=...)`.
- Proportion: one task per deliverable, bodies left to the implementer except where the plan pins behavior.
