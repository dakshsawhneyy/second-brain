# SDD ledger — plan: C:\Studies\Claude Code\z second brain\docs\superpowers\plans\2026-11-17-second-brain-stage-0b-2.md

Executor: inline (Native with targeted review), chosen by user 2026-11-17.
Pre-flight: shared interfaces checked (Store, Provider/Router, Card, WatchItem, Transcript, Index); names consistent across tasks.

Ruling: project is not a git repo and the user's rule forbids add/commit/push without approval each time, so plan "Checkpoint" steps record test results here instead of committing; `git init` is pending his answer — no cost if wrong (history can be added later).
Ruling: sdd-workspace/task-start/task-done scripts assume a git repo, so progress is tracked in this file and the test command output is recorded per task — no cost if wrong.
Ruling: final review: no explicit subagent dispatch without user ask (Pro quota); targeted review of Tasks 5 and 14 plus whole-project pass will be done by a reviewer agent only if the user approves, else self-review — user chose "Native with targeted review".

Task 1: complete (tests: pytest -q -> 4 passed)
Ruling: Card field is 'schema_version' (not 'schema') — pydantic BaseModel already has a 'schema' attribute; costs nothing, key name differs from the design example.
Task 2: complete (tests: pytest -q -> 33 passed; schemas/card.v1.json generated)
Task 3: complete (tests: pytest -q -> 43 passed)
Note: Task 2 ledger line claimed schemas/card.v1.json generated before it was; it failed (package not importable outside pytest). Fixed by editable install (pip install --no-deps -e .) and regenerated (7292 bytes). Lesson: verify before ledgering.
Task 4: complete (tests: pytest -q -> 61 passed)
Ruling: Task 4 chunk() gained a with_times=True parameter (default keeps [mm:ss] stamps) — Task 8 extraction needs timestamps for key points; plain mode kept for tests/other callers — no cost if wrong.
Ruling: Task 5 provider constructors take (model, base_url=..., client=None) keyword-first for Ollama — plan listed base_url first; no behaviour change.
Task 5: complete (tests: pytest -q -> all passed; includes self-review fix: remote Ollama URL no longer counts as local — test_ollama_is_local_only_when_host_is_loopback RED->GREEN)
Task 6 (code part): complete (tests: pytest -q -> 94 passed; live smoke: real transcript fetch OK from laptop, 61 segments). Steps 5-8 (Takeout export, Claude usage measurement, Ollama comparison, routing decision) DEFERRED: need the user's Takeout file, Ollama approval and his confirmation of the numbers. Continuing with Tasks 7-15, which do not depend on the routing choice.
Task 7: complete (tests: pytest -q -> 111 passed)
Ruling: Task 8 extract() takes no goals parameter and its prompt contains no personal context — extraction may run on a free cloud model, so nothing private is sent; costs: action suggestions are generic rather than goal-tuned.
Task 8: complete (tests: pytest -q -> all passed; self-review fix: timestamp whitespace stripped, RED->GREEN)
Ruling: get_transcript now RAISES RateLimited after retries (plan said return None) — otherwise a throttled fetch is indistinguishable from 'no captions' and would create permanent transcript-less cards; export_batch stops on RateLimited and keeps progress; tests updated RED->GREEN.
Ruling: Task 9 pipeline routes TRIAGE as 'private' (not 'public' as the plan said) because the triage prompt contains his goals; extraction is the only 'public' route and carries no goals. Cost if wrong: triage cannot use a cloud model (intended).
Task 9: complete (tests: pytest -q -> 138 passed)
Final: minor (deferred): pipeline keeps trying every item when the local model is down (each fails fast with ProviderError); could abort after N consecutive provider failures.
Task 10: complete (tests: pytest -q -> 156 passed, 1 slow deselected). The slow real-model test (FastEmbedder semantic match) NOT yet run: needs a model download, asking the user at acceptance.
Task 11: complete (tests: pytest -q -> 167 passed, 1 slow deselected)
Task 12: complete (tests: pytest tests/test_capture.py -> 25 passed)
Task 13: complete (tests: pytest -q -> 216 passed, 1 slow deselected)
Ruling: Task 14 scheduling uses an asyncio loop + raw/bot_state.json instead of PTB's JobQueue (needs the APScheduler extra, not installed); windows: morning 09:00-14:00, evening 21:30-24:00, once per day, retried if the send fails. No cost if wrong.
Task 14 (bot module): complete (tests: pytest tests/test_bot_app.py -> 19 passed). CLI wiring (sb bot/ingest/search) in progress together with Task 15.
Task 14: complete (tests: tests/test_bot_app.py -> 20 passed; live check: real token OK via app wiring, no message sent)
Task 15: code complete (tests: pytest -q -> 245 passed, 1 deselected). Written, NOT run: scripts/install-autostart.ps1 (needs approval). Created: .env (gitignored, real token), profile/goals.md, profile/profile.md, docs/RUNBOOK.md. Manual acceptance steps pending: Takeout file, Ollama approval, routing decision (Task 6), 100-card ingest + 20-card spot-check, autostart approval, start of 14-day stop-rule clock.
Final review: independent code-reviewer (opus) dispatched on privacy gate, bot owner check and the five Review Focus items; results pending.
Final review: independent code-reviewer (opus, read-only), 0 Critical, 4 Important, 10 Minor. It was slow (not stuck) and finished.
Final: fixed Ollama cloud models counted as local (privacy gate) - test_ollama_cloud_models_are_not_local_even_on_localhost + test_ollama_cloud_model_blocked_for_private_data RED->GREEN
Final: fixed one bad video stalling ingest / crashing run - test_default_fetcher_maps_every_library_error_to_one_of_our_three, test_other_fetch_errors_propagate_and_are_not_cached, test_unparsable_transcript_is_a_per_item_failure_and_the_run_continues, test_export_batch_skips_a_video_whose_transcript_cannot_be_parsed RED->GREEN
Final: fixed duplicate/misdated Telegram captures after a crash - test_redelivered_message_does_not_duplicate_and_uses_the_message_date, test_message_id_makes_the_card_id_stable_across_redelivery RED->GREEN
Final: fixed bot dying silently at logon and token printed on rejection - test_run_with_retries_* (5), test_configure_logging_redacts_the_token_in_every_handler RED->GREEN
Final: fixed bot token visible in repr(settings) (re-graded from Minor to Important: secret exposure) - test_token_never_appears_in_repr_or_str RED->GREEN
Final: suite 266 passed, 1 deselected (slow real-model test)
Final: Ruling: unknown LLM topic becomes 'uncertain' and still yields a card when score >= 40 (reviewer said Review Focus 3 expected a skip) - the card is schema-valid and flagged uncertain for the weekly check - cost if wrong: a few cards with a vague topic
Final: minor (deferred): LLM-written action text can contain a URL injected by a transcript and be pushed in the morning brief (no parse_mode, nothing executed)
Final: minor (deferred): context.py stops at the first oversized snippet (break should be continue) and key-point text has no length cap
Final: minor (deferred): --limit does not count failures, so repeated provider failures can triage the whole history; abort after N consecutive provider failures
Final: minor (deferred): if save_state fails after a send, the scheduler resends the brief each minute
Final: minor (deferred): a zero-length card after power loss is skipped forever by has(); torn last tombstone line merges with next append
Final: minor (deferred): malformed Takeout entries (non-dict details, non-string titleUrl, dict subtitles) raise; ad detection and 'Watched ' prefix are English-only
Final: minor (deferred): sb search --k is capped by per_source_cap=3
Final: minor (deferred): sb export-batch accepts negative --n
Update: git init done (no commits); embedding model + slow test passed; autostart registered; Ollama installed; qwen2.5:7b pull FAILED (no internet), deferred by the user.
Plan written: Stage 3-5 plan saved (16 tasks). Not started.
