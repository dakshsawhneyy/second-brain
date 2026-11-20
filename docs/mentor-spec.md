# Mentor: design spec (strict check-in mentor on Telegram)

Status: DRAFT for Daksh's review. Nothing here is built. Date: 2026-11-19.
Inputs: docs/vision-additions-2026-11-19.md (wanted feature 2), design.md section 6, decisions.md, the Stage 3-5 plan.
Persona prompt text: docs/mentor-persona-prompt.md (loaded as a file; not repeated here).

Recommendation first: build a small mentor (commitments, evidence, evening review, weekly review) with code doing the
analysis and the local 7B model only phrasing messages. Run it in shadow mode for 7 days to get a baseline. Add penalties
only in week 3, and only if the ledger shows he keeps missing. Section 9 explains why, and what to cut.

## 0. Hard rules (apply to every section)
- R1 Free only. Local Ollama `qwen2.5:7b`. No paid API, no new paid service.
- R2 Private data (goals, feelings, money, check-in answers, commitments, miss reasons) goes only to a local model.
  New router task `mentor`, always called as `router.route("mentor", "private")`. A non-local provider raises `SensitivityError`.
- R3 Read-only toward his other apps. The mentor never opens, lists, reads or runs anything under
  `C:\Studies\Claude Code\startup_finder`. The only SkipATS signal is the optional inbox file in 4.4, which Daksh writes
  himself or produces with his own script. That script is out of scope and needs his explicit yes (vision doc).
- R4 No secrets anywhere: not in prompts, logs, cards, the ledger or the context pack. The token stays in `.env`.
- R5 The mentor never runs git write commands. Evidence uses only `git log` (4.2).
- R6 Owner chat only (`is_owner` plus the `only_owner` filter, unchanged).
- R7 Telegram privacy (resolves the conflict with decisions.md #9 and the Stage 3-5 global constraints). Telegram is
  a third-party server, not a model, but bots are not end-to-end encrypted. Outbound mentor messages may contain only
  (a) text Daksh himself sent through Telegram (commitments, answers, excuses), (b) counts, dates and card ids,
  (c) repo names from his allowlist and commit subjects, (d) penalty menu text he approved. Never: goals.md figures,
  profile.md text, or the text of `thought`, `book`, `decided` or chat-derived cards. He accepts that his own replies
  already sit on Telegram's servers. The weekly context pack for Claude (6.4) never goes through Telegram.

## 1. Purpose and success metric

Purpose: increase what he ships toward the two bets, by making daily commitments explicit, checking them against evidence,
and showing the pattern bluntly. Ties to the system mantra: "increase what he ships, or shrink or kill it".

Measured weekly (ISO week, Asia/Kolkata), all computed by code from the ledger and cards:

| Metric | Definition | Target after 3 weeks |
|---|---|---|
| Applications sent | `applied:` captures in the week (+ SkipATS inbox `sent` if present) | above baseline, and at least 10/week (proposed default, not his number yet; he sets it in 4.3) |
| Things shipped | commitments with status `kept` at level corroborated or verified, plus `made:` cards with evidence | above baseline |
| Commitment keep rate | kept / (kept + missed), days with status `no_data` excluded | at least 0.6 |
| Evidence rate ("honesty rate") | claims at corroborated or verified / all claims that could have evidence | at least 0.7 |
| Response rate | mentor prompts he answered within 3 h / prompts sent | at least 0.6 |

Honest limit: no system can measure honesty. "Evidence rate" is a proxy: the share of claims backed by something the system can
see. Lies that come with fake evidence (empty commits) are caught only by the weekly sample check (6.3).

Baseline: week 0 is shadow mode (11.1): commitments are asked and recorded, evidence is collected, but there are no nudges,
no escalation and no penalties. Week 0 numbers are the baseline.

Stop rule for the mentor (separate from, and after, the 14-day brief clock; see 7.9): after 21 days live, if shipped/week AND
applications/week are both not above baseline, or the response rate is under 0.4 for 7 days in a row, cut the mentor down to
the weekly review only. Record the decision in docs/decisions.md.

## 2. Persona and message generation

### 2.1 Persona
Text: docs/mentor-persona-prompt.md. Character: strict, direct, short, evidence-first. It is an AI and says so if asked.
It may use general principles of high performers (small daily outputs, ship before polish, measure, cut what does not work)
but never claims to be rich, a founder or a person, never tells first-person stories and never quotes a named person unless the
quote is in FACTS. It criticises behaviour and plans, never his traits. It never invents facts about him (every reference
carries a card id, enforced in 2.5).

### 2.2 Division of labour (the key design choice)
A 7B model cannot be trusted to analyse. So: code decides WHAT to say (intent, facts, level, penalty); the model decides only
HOW to phrase it. Variety comes from his real data changing every day, plus model phrasing at temperature 0.7, not from a list.

### 2.3 Prompt assembly (code, `mentor/prompt.py`)
Prompt = persona (system) + FACTS block + last 4 turns of the current conversation + TASK line. Budget: under 2 500 tokens total
(qwen2.5:7b context is fine; 6 GB VRAM latency stays about 3-10 s). FACTS lines, newest first, at most 15:
```
[mc_20261119_1] commitment today: "send 3 applications to infra startups" status=open evidence=none bet=job
[mc_20261118_2] commitment yesterday: "finish terraform module README" status=missed reason="got distracted by YouTube"
[g_3f9a1c2] commit homelab 2026-11-19 11:42 "add prometheus alert rules"
[tg_5521] applied: Acme Infra | SRE intern | link given
pattern: missed 3 of last 7 days; 2 miss reasons in category distraction
streak: 2 days kept in a row
```
FACTS sources: today's and yesterday's commitments, open commitments carried over, last 3 answers, git evidence of the mentor
day, `done:`/`made:`/`applied:` cards of the day, computed pattern lines (2.4). Ids: card ids as in the store; git evidence
uses `g_<first 7 of hash>`. Never in FACTS: goals.md, profile.md, thought/book/decided/chat card text, money figures.

### 2.4 Intent selection (pure code, `mentor/intents.py`)
Each scheduled or reactive message picks exactly one intent by the first matching rule:

| Order | Condition | Intent |
|---|---|---|
| 1 | supportive mode active (7.3) | `checkin_supportive` |
| 2 | morning, no commitment yet | `ask_commitment` (mention yesterday's result in one clause) |
| 3 | commitment is vague (no verb from the output list, or contains learn/explore/work on/study) | `sharpen_commitment` |
| 4 | more than 3 items committed, or keep rate of last 7 days under 0.5 with 3 items | `cut_scope` |
| 5 | claim with evidence `claimed` that could be checked | `ask_proof` |
| 6 | same miss category 3+ times in 7 days | `name_pattern` |
| 7 | item carried over 3+ times | `kill_or_split` |
| 8 | no job-bet item in 5 days, or no product-bet item in 10 days | `bet_imbalance` |
| 9 | evening, items open | `evening_review` |
| 10 | otherwise | `next_step` |

The output verb list: send, ship, commit, publish, deploy, apply, write (with a named artifact), call, message, demo, record.

### 2.5 Guards after generation (code, `mentor/guards.py`)
Reject and regenerate once (temperature 0.9), then fall back to the intent's template (2.6) if any check fails:
1. More than 90 words, or contains `!` or an emoji.
2. Any bracketed id not present in FACTS (hallucinated history).
3. Any number with 2+ digits not present in FACTS or TASK (invented figures).
4. Banned phrases (case-insensitive): great job, amazing, awesome, proud of you, well done, keep it up, you got this,
   billionaire, millionaire, as a founder, when I was, I built, I started, my company, I remember, "as <Name> said".
5. Penalty text appears but TASK had `penalty=none`, or differs from the approved menu text.
6. Unsafe advice, matched as whole phrases with word boundaries (so "fail fast", "ship fast" and "invest time" pass):
   sleep less, skip sleep, no sleep, all-nighter, skip a meal, skip food, skip dinner, stop eating, go without food,
   take a loan, borrow money, invest money, bet money, put your savings.
7. Anti-repetition: trigram Jaccard similarity above 0.5 with any of the last 14 outbound mentor messages, or the same first
   4 words as any of the last 5 (those openings are also passed in TASK as `avoid_openings`).
Every rejection is logged as counts only (`raw/mentor/guard.log`: ts, intent, rule number), never the text.

### 2.6 Templates (fallback, and the whole bot when Ollama is down)
One to three short templates per intent with slots filled by code, for example `ask_proof`:
"You marked [{id}] done. I see no commit or link for it. Send the hash, link or file name, or it stays as claimed."
Templates keep the bot working with no model at all. The test suite runs on templates plus a fake provider.

### 2.7 Message budget (anti-nag)
- Unprompted messages (everything the bot sends without being asked, including the existing morning brief, resurfacing and the
  weekly review) are capped at 4 per mentor day. Daily cap order of priority: morning > evening > weekly > midday > resurfacing.
- Replies to his messages do not count, but at most one follow-up question per reply.
- If he ignores 2 prompts in a row, the next unprompted message is the evening review only (no midday nudge that day).
- Free chat: `/m <text>` or replying to a mentor message. Rate limit 20 model calls per hour; above that, templates only.

## 3. Daily check-in

### 3.1 Clock
- Timezone Asia/Kolkata for everything. Mentor day = 04:00 to 03:59 next day, so a 00:30 commit counts for the previous day.
- Quiet hours 23:00-10:00: no unprompted messages. Replies to his own messages are still allowed.
- Rest day: one per week, chosen by `/restday <weekday>` (default Sunday). No commitments asked, no misses, no penalties;
  the weekly review goes out that day.
- `/quiet <hours>` (max 4) silences unprompted messages; used more than 3 times in a week is reported in the weekly review.

### 3.2 Morning commitment (merged with the existing brief)
- Fires in the existing window (09:00-14:00, first scheduler tick after the laptop is on and quiet hours end). One message:
  the existing brief lines (focus, yesterday titles, one action) followed by the mentor part. No second morning message.
- Mentor part: intent `ask_commitment` -> "State 1-3 outputs for today."
- He replies with 1-3 lines (numbered or one per line). Parser (`mentor/commit.py`, pure): split on newlines or `1)`/`1.`/`-`;
  max 3 items (extra items are dropped and the reply says so); each item gets a bet tag from a `#job` / `#product` / `#other`
  hashtag, else from keywords (apply, interview, resume, outreach -> job; landing, customer, pricing, validate -> product),
  else `other`.
- Vague items (2.4 rule 3) get one `sharpen_commitment` reply; his next answer replaces the item. If he does not sharpen it,
  the item stays and is marked `vague=true` (counts in the weekly review).
- Each item becomes a `commitment` card (3.5). Reply: one line confirming, listing ids.
- He can commit later in the day with `/commit <items>`; a commitment made after 18:00 is marked `late=true`.

### 3.3 Midday nudge (conditional)
Fires once between 14:00 and 17:00 only if ALL hold: not rest day, not supportive mode, under the daily cap, and nothing was
logged since 04:00 (no commitment, no `done:`/`made:`/`applied:` card, no allowlisted commit). Intent `ask_commitment` or
`next_step`. Otherwise skipped silently.

### 3.4 Evening review (replaces `build_evening_checkin`)
- Fires in the existing evening window (from 21:30). Intent `evening_review`. The message lists today's items with id, status
  and evidence level, then asks for each open item: done (with proof) or missed (with one-line reason).
- Reply grammar (also accepted any time with `/close`): `1 done <hash|link|file>` / `2 missed <reason>` / free text.
  Free text is mapped by the local model into the same structure via `complete_json` into
  `CloseOut(items: list[{index:int, status:"done"|"missed", proof:str|None, reason:str|None}])`; on failure the bot asks for
  the short grammar instead of guessing.
- Miss reasons are classified (local model, fixed list, `complete_json`) into: `scope_too_big`, `distraction`,
  `unclear_next_step`, `avoided_hard_part`, `external`, `energy_health`, `other`. `energy_health` with any safety keyword
  (7.3) starts supportive mode.
- Items not closed by 03:59 become `missed` with `reason=null` and `auto_closed=true`. They count as missed for the keep rate.
  They count as "no reason given" for the penalty triggers (5.3) only if the evening review was actually delivered and he had
  at least 90 minutes before 03:59 to reply; otherwise the day is `no_data` for penalty purposes. If the bot was off at 03:59,
  the auto-close runs on the next tick but never fires a penalty (no retroactive penalties).
- Also asked once in the evening: "What did you learn or read today?" stays as one optional line (keeps the existing book
  capture habit); answers use the existing `book:` / `idea:` capture.

### 3.5 Cards and schema change
New card types `commitment` and `checkin`, plus one optional sub-object. All mentor cards are `visibility="private"`, forced
by a validator (a mentor card can never become publishable, so it never reaches the Stage 3-5 feed).

```python
class MentorMeta(_Strict):
    day: date                                   # mentor day (3.1)
    item: int | None = Field(None, ge=1, le=3)  # position in the day's commitment
    status: Literal["open", "kept", "missed", "dropped"] = "open"
    evidence: Literal["claimed", "corroborated", "verified"] | None = None
    evidence_refs: list[str] = Field(default_factory=list, max_length=10)  # card ids, g_<hash>, links, file names
    bet: Literal["job", "product", "other"] = "other"
    miss_category: str | None = None           # one of the 3.4 list
    reason: str | None = Field(None, max_length=300)
    vague: bool = False
    late: bool = False
    auto_closed: bool = False
    carried_from: str | None = None             # id of the commitment it continues
```
- `Card.type` Literal gains `"commitment"` and `"checkin"`; `CARD_TYPES` too. `Card` gains `mentor: MentorMeta | None = None`.
- `commitment` card: id `mc_<YYYYMMDD>_<n>`, title = the item text (80 chars), `key_points=[]`, `source="mentor"`,
  `consumed_at` = time he stated it, topic `uncertain`.
- `checkin` card: one per evening close-out, id `mk_<YYYYMMDD>`, title "Evening review <date>", key points = his raw answer
  lines (private), `mentor.day` set.
- Existing `done:` (acted), `made:` (produced) cards are reused as evidence; no parallel types. New capture prefix
  `applied: <company> | <role> | <proof>` -> type `acted`, title "applied: <company>", key point "<role>", and the proof in
  `url` when it is a link. This keeps the application count out of a new type.
- Version decision: additive change, stays `card.v1`. Argument against design.md 7 ("breaking changes bump the version"):
  no existing field changes meaning, old cards stay valid, and the only consumers (his X/LinkedIn tools) read the publishable
  feed, which can never contain mentor cards. The one break is that a strict external validator built from the old
  `schemas/card.v1.json` would reject the new type values; acceptable because no such consumer reads private cards. Regenerate
  `schemas/card.v1.json` and note the change in decisions.md. If he disagrees, bump to `card.v2` with the same content.
- Stage 3-5 lifecycle: `is_protected` already protects every `type != "consumed"`, so mentor cards are never demoted.

### 3.6 Bot offline vs ignoring
The bot only runs while the laptop is on. The scheduler writes `last_tick` to `raw/bot_state.json` every tick.
- A mentor day with no tick between 10:00 and 23:00 is `no_data`: not a miss, no escalation, no penalty, shown separately in
  the weekly review (a run of 3 `no_data` days is itself reported).
- After a restart, at most one catch-up message ("Bot was off since <date>. State today's outputs."). Never several queued
  messages, never retroactive penalties.

### 3.7 Tone escalation ladder (code, `mentor/ladder.py`)
Level is computed fresh each day from the last 7 mentor days (excluding rest and `no_data` days):

| Level | Trigger | Tone given to the model (TASK level) |
|---|---|---|
| 0 | default | neutral, factual |
| 1 | yesterday missed or no commitment | names the miss with id, asks what changes today |
| 2 | 2 consecutive misses, or 3 misses in 7 days | blunt; names the pattern and the repeated reason category; demands one minimum output before noon |
| 3 | a penalty trigger fired (5.3) | states the approved penalty, asks for an explicit "accept" or `/appeal` |

Ceiling: there is no level 4. If misses continue past level 3 for 3 more days, the intent switches to `cut_scope` with the
message that the plan is wrong, not only him: commit to one item per day for the next 3 days. Harshness never increases further.
De-escalation: each day with all items kept at corroborated or better drops one level.

## 4. Evidence check

### 4.1 Levels
| Level | Meaning | Mentor says |
|---|---|---|
| claimed | only his word | "Logged as claimed. Not counted as shipped until there is proof." (+ `ask_proof` once, never twice for the same item) |
| corroborated | an artifact the system can see matches the day and the item loosely | states it plainly, no praise: "Corroborated by [g_3f9a1c2]." |
| verified | an artifact matches exactly (see rules) | "Verified: [g_3f9a1c2] homelab 11:42." |

Matching rules (`mentor/evidence.py`, pure functions over inputs):
Each item has a kind from its text: `code` (commit, ship, deploy, fix, PR, module), `application` (apply, application,
outreach, sent), `content` (post, publish, write-up), `other`. "Verified" needs a locally checkable artifact of the matching kind:
- verified: `code` item -> he gives a commit hash (7-40 hex) that exists in an allowlisted repo with author date inside the
  mentor day; `application` item -> a proof file (screenshot or exported email) he named that exists under `raw/proof/`
  with a modified time inside the mentor day. `content`/`other` items cannot reach verified.
- corroborated: a `code` item with an allowlisted commit inside the mentor day whose subject shares at least one keyword
  (3+ letters, stop-words removed) with the item text; any item with a link he gives (links are never fetched, so a link,
  even to his own profile, is at most corroborated); an `application` item whose `applied:` count is matched by the SkipATS
  inbox `sent` number for that week.
- claimed: nothing above. His own capture cards (`done:`, `made:`, `applied:` without a proof) are claims, not evidence.
- Shipped counts use only corroborated + verified. Claimed items are shown, never counted.

### 4.2 Git reader (read-only)
- Command, exactly: `git --no-pager -C <repo> log --since=<iso> --until=<iso> --no-merges --format=%H%x1f%aI%x1f%s`,
  with env `GIT_OPTIONAL_LOCKS=0`, `GIT_TERMINAL_PROMPT=0`, timeout 10 s, `shell=False`. Optionally `--author=<email>` from
  config. Nothing else is ever run: no status, fetch, pull or any write. Errors -> that repo is skipped and the weekly review
  reports "repo unreadable".
- The runner is injected (`run: Callable[[list[str]], str]`), so tests use fake output. No test creates a repo or a commit.
- Commit subjects are capped at 120 chars and passed through the Stage 3-5 `redact_secrets` (Task 13) once it exists; until
  then subjects containing `token`, `key=`, `password` are replaced by "(subject hidden)".

### 4.3 Allowlist config `profile/mentor.json` (no secrets; hand-edited by him)
```json
{
  "repos": ["C:\\Studies\\Claude Code\\z second brain", "C:\\Projects\\homelab"],
  "git_author_emails": ["his-email@example.com"],
  "own_link_hosts": ["github.com/dakshsawhneyy"],
  "rest_day": "sunday",
  "applications_weekly_target": 10,
  "money_cap_inr_per_week": 0
}
```
Validation (`mentor/config.py`): resolve each path (`Path.resolve()`), compare case-insensitively (Windows); reject an entry
that equals, is inside, or is a parent of `C:\Studies\Claude Code\startup_finder` (hard-coded deny, also any path whose
resolved form contains `startup_finder`); reject non-existing paths and paths without `.git`; reject drive roots. A rejected
entry is dropped with a warning; the bot never fails because of it.

### 4.4 Optional SkipATS inbox (one-way, read-only, he controls it)
File `raw/inbox/skipats.jsonl`, written by him (typed) or by his own read-only script outside this project. The mentor only
reads this file; it never knows or touches the SkipATS path. One line per week or per day:
```json
{"week": "2026-W47", "sent": 12, "replies": 2, "commit_subjects": ["add retry to scraper"], "source": "manual"}
```
Unknown keys ignored, bad lines skipped, `sent`/`replies` must be 0-500 ints. Used only for counts in the weekly review and as
corroboration for `applied:` items (`sent` total vs his `applied:` count; a mismatch over 30% is reported, not punished).
Absent file = feature off.

### 4.5 Lying and gaming
- Contradiction: he says done, evidence stays `claimed`, and later says it was not done -> `admitted_false` on the item
  (counts as missed, triggers 5.3 rule c only if not admitted the same day). Admitting the same evening is free: honesty is
  never punished harder than the miss itself.
- Disbelief is allowed: for a claimed item of a checkable kind (code, application, post) the mentor says once that it does not
  count it and asks for proof. It never calls him a liar; it states what it can and cannot see.
- Repeated claimed-only days (3+ in 7) become the `ask_proof` intent and a weekly review line.
- Gaming signals reported weekly (not punished): commits under 3 changed lines are not available from `--format` alone, so
  instead: share of corroborating commits with subjects of 1-2 words, commits clustered in the 10 minutes before the evening
  review, and items that are copies of yesterday's text. The deeper check is human: the weekly Claude pack (6.4) includes 3
  random corroborated items for him to defend.

## 5. Pre-committed penalties

### 5.1 Principle
The mentor never invents a penalty. Code picks one from a menu he wrote and approved. The real lever is the visible record;
penalties are a small extra, on his honour, and they start only in week 3 (section 9).

### 5.2 Menu file `profile/penalty-menu.json` (he writes it; example)
```json
{
  "version": 1,
  "items": [
    {"id": "p1", "severity": 1, "text": "No YouTube entertainment or games tomorrow until 20:00"},
    {"id": "p2", "severity": 1, "text": "Extra task tomorrow: send 2 more applications than committed"},
    {"id": "p3", "severity": 2, "text": "Write a public-commitment note in the weekly review explaining the miss"},
    {"id": "p4", "severity": 2, "text": "Donate Rs 100 to a charity I choose, and log the receipt file name"},
    {"id": "p5", "severity": 2, "text": "Leisure item (series episode) delayed by 2 days"}
  ]
}
```
Validation, item level (a bad item is dropped with a reason; the menu needs 2-10 valid items to be approvable): text 10-160
chars, severity 1 or 2. An item is rejected if it matches the forbidden list (whole words): sleep, wake, food, meal, eat,
fasting, water, medicine, exercise, run, workout, pushup, family, friends, loan, borrow, credit. An item with a money amount
above `money_cap_inr_per_week` (default 0) stays in the file but is inactive until he raises the cap. Exercise is excluded
on purpose: it must not become punishment.

### 5.3 Approval and triggers
- `/penalties` shows the menu and its SHA-256 (first 12 hex). `/penalties approve <hash12>` records approval in the ledger.
  Any change to the file changes the hash; the menu is then inactive until re-approved. The bot can never edit the menu.
- Penalties are active only if: an approved menu exists, `SB_MENTOR_PENALTIES=on`, not rest day, not supportive mode,
  not a `no_data` day, not shadow week.
- Triggers (evaluated once per mentor day at the evening close or the 03:59 auto-close):
  a. All items of the day missed and no reason given for any.
  b. No commitment for 2 consecutive non-rest days on which the bot was running.
  c. An item admitted false after being reported done on an earlier day.
- Selection: severity 1 for the first trigger in a week, severity 2 for the second; within a severity, round-robin by id.
- Caps: at most 1 penalty per day and 2 per ISO week. A third trigger in a week is recorded only (`capped`).
- Money: total of money items per week never above `money_cap_inr_per_week`; selection skips money items when the cap is used.

### 5.4 After a penalty fires
- Message (ladder level 3) carries the exact menu text and asks: `/accept <pid>` or `/appeal <pid> <reason>`.
- `/served <pid>` marks it done (honour). Not served within 48 h -> `unserved` and listed in the weekly review. No stacking:
  an unserved penalty never creates another penalty.
- Appeal: max 1 per ISO week. Granted automatically if the reason is at least 20 chars, with a cost: the next day must have at
  least one item kept at corroborated or better, else the penalty is reinstated (`appeal_failed`). A second appeal in the same
  week is refused with a pointer to this rule.
- Skip: `/skip <pid>` is always possible (it is his choice) but has a fixed cost: the ladder rises one level (max 3), the
  week's appeal is used up, the next trigger that week goes straight to severity 2, and the skip is listed by name in the
  weekly review. Two skips in a row -> the weekly review asks whether to keep penalties at all.
- Supportive mode (7.3) pauses everything and voids penalties not yet served.

### 5.5 Ledger file `mentor/penalties.jsonl` (append-only, atomic append, in the private repo)
One JSON object per line; state is derived by replaying events.
```json
{"ts":"2026-12-03T22:40:11+05:30","event":"menu_approved","menu_hash":"a1b2c3d4e5f6","menu_version":1}
{"ts":"2026-12-04T23:59:00+05:30","event":"triggered","pid":"p1","rule":"a","day":"2026-12-04","refs":["mc_20261204_1","mc_20261204_2"],"menu_hash":"a1b2c3d4e5f6"}
{"ts":"2026-12-05T10:15:02+05:30","event":"accepted","pid":"p1","day":"2026-12-04"}
{"ts":"2026-12-05T21:00:00+05:30","event":"served","pid":"p1","day":"2026-12-04"}
{"ts":"2026-12-06T23:59:00+05:30","event":"capped","rule":"b","day":"2026-12-06"}
```
Events: `menu_approved`, `triggered`, `accepted`, `served`, `unserved`, `appealed`, `appeal_failed`, `skipped`, `voided`,
`capped`, `paused`, `resumed`. Required keys: `ts` (aware), `event`; `pid`, `day`, `rule`, `refs`, `menu_hash`, `reason`
(max 300 chars) as the event needs. Unreadable lines are skipped and counted.

## 6. Blunt weekly review

### 6.1 One Sunday message
Built inside the Stage 3-5 Task 7 weekly builder (not a second message): the existing metrics part, then a mentor part.
Code computes every number; the local model writes only the three "verdict" sentences and the 3 questions, under the same
guards (2.5). Max 3 500 chars.

### 6.2 Template (mentor part)
```
Week 2026-W48 (rest day Sun, 1 no-data day)
Commitments: 14 made, 8 kept (5 verified, 3 corroborated), 5 missed, 1 dropped. Keep rate 0.62 (last week 0.50).
Claimed only: 2 [mc_..., mc_...]
Shipped: 8 items, 23 commits in 3 repos. Applications: 6 (target 10). SkipATS inbox: sent 12, replies 2.
Bets: job 9 items, product 1, other 4. Product bet untouched since [mc_20261121_2].
Time realism: you commit 2.8 items/day and keep 1.6. Next week: commit 2.
Repeated reasons: distraction x3 [..], scope_too_big x2 [..].
Carried 3+ times: "landing page copy" [mc_...] -> kill it or split it.
Penalties: 1 fired, served. 0 appeals. Supportive mode: 0 days. /quiet used 1 time.
Verdict: <3 sentences, model, guarded>
Stop: <rule-based: the most-carried item, or the lowest keep-rate bet>
Do next week: <rule-based: commitment count, bet to raise, one concrete item type>
Answer these 3 (reply /answer 1 ...):
1. <from the worst finding>
2. <from the bet imbalance>
3. <from the most repeated miss reason>
```
Answers become one `checkin` card `mw_<YYYY-Www>`; next week's FACTS include them.

### 6.3 Analysis method (code, `mentor/weekly.py`)
- Keep rate, verified share, claimed list: from commitment cards of the week.
- Time realism: mean items committed vs kept per active day; recommend `max(1, round(mean kept))` items next week.
- Repeated excuses: count `miss_category`; any category with 2+ in the week is named with ids.
- Bet balance: share of items per bet; flag a bet with 0 items in 7 days, or job share under 0.5 while applications are under
  target (his near-term income depends on bet 1).
- Stop list: items carried 3+ times; recurring commitment texts never kept (fuzzy match, ratio over 0.8).
- Gaming signals (4.5) and the SkipATS mismatch line when present.
- Three questions: one per top finding by fixed priority (worst keep-rate drop > bet imbalance > repeated reason > carried item).

### 6.4 Deep review: context pack for his own Claude session
`sb mentor-pack --week 2026-W48` writes `raw/packets/mentor-2026-W48.md` (local only, gitignored, never sent by the bot):
profile.md, goals.md, the week's commitment and checkin cards (text), penalty events, metrics, the local review text,
4 weeks of trend numbers, 3 random corroborated items to defend, and instructions for Claude ("act as a blunt reviewer; find
the one change with the most leverage on the two bets; challenge the plan; reply with the JSON below"). He opens a Claude
session himself and pastes or attaches the file. This is the one deliberate exception to R2 and it is his act, not the
system's: the CLI prints a warning and needs `--i-understand-this-leaves-the-laptop`. By default the pack excludes supportive
mode notes and `energy_health` reasons, and strips every goals.md line containing a currency amount (Rs, lakh, USD, $, INR);
`--include-money` keeps those lines. Claude's reply can be imported
with `sb mentor-import FILE` into one `checkin` card (`mx_<week>`), validated with pydantic, so its advice becomes FACTS.

## 7. Failure modes and honest limits
1. 7B weakness: bland, repetitive, sometimes off-topic. Mitigation: code chooses intent and facts; guards; templates. Accept
   that it will feel like a sharp templated coach, not a human. Measure: guard rejection rate in the weekly review; if over
   40%, drop the model for that intent and use templates.
2. Hallucinated history: guard 2 (ids) and 3 (numbers). The model never sees cards outside FACTS. Every statement about his
   past must carry an id, or the message is regenerated or replaced by a template.
3. Sycophancy drift: banned-phrase guard; temperature only on the mentor route; quarterly he reads 20 random mentor messages
   (`sb mentor-sample 20`). Also the opposite drift (contempt): guard on insult words (lazy, pathetic, loser, useless, stupid).
4. Harshness and burnout, safety valve:
   - `/unwell [text]` starts supportive mode instantly, no questions: 48 h (extend with `/unwell` again), penalties paused
     and unserved ones voided, ladder reset to 0, one gentle check-in per day, no numbers. Ends early with `/back`.
   - Automatic detection (code, word-boundary phrase match) only ASKS, with buttons "Switch to supportive mode? Yes / No":
     phrases "I am sick", "feeling sick", fever, hospital, injured, overwhelmed, burnt out, burned out, panic attack,
     anxiety attack, can't cope, mental breakdown, family emergency, death in the family. Plain "panic", "breakdown" or
     "sick" are not matched, because "kernel panic" and "cost breakdown" are normal words in his work.
   - Crisis phrases (suicide, kill myself, want to die, self harm, self-harm, end it all, end my life) -> mentor mode stops,
     no button, the bot sends once: "Please
     talk to someone now. Tele-MANAS, free and 24x7: 14416 or 1-800-891-4416. If you are in danger, call 112." (numbers checked
     2026-11-19). The mentor stays off until `/back`.
   - The valve is never penalised and never questioned. Uses are counted; more than 2 starts in 14 days is shown neutrally in
     the weekly review so he can see it, nothing else.
5. Goodhart: commits and applications reward volume. Mitigation: shipped counts only items he committed to in the morning
   (not raw commit counts); applications are counted but replies are shown next to them; gaming signals (4.5) are shown, not
   punished; the Claude pack asks him to defend 3 random items.
6. Privacy leaks: R2 router gate with its own `mentor` task (never `synthesis`, which may become cloud after Plan A/B);
   R7 outbound filter tested with marker strings; guard log has counts only; context pack local and opt-in.
7. Telegram limits: one chat, a few messages a day, far under the 1 msg/s per chat limit. On `RetryAfter` wait and retry once,
   then mark unsent; the scheduler retries on the next tick (existing behaviour). Messages over 4 096 chars are cut at a line.
8. Ollama down or slow: 30 s timeout on the mentor call (send the "typing" action first), then the template. Never silent.
9. Experiment confound: the 14-day brief stop-rule clock (NEXT_STEPS A.7) has not started. Running the mentor inside it makes
   both unreadable. Decision proposed: run the 14-day brief clock first with the mentor in shadow mode (it records, does not
   push), then 21 days of the live mentor measured by section 1. If he wants it sooner, declare one combined experiment with
   one metric (shipped/week) and accept that we cannot tell which part helped.
10. He controls everything (he can edit files, stop the bot). This is not fixable and is stated, not hidden: the mentor is a
   mirror and a referee he hired, not an enforcer.

## 8. Implementation plan (TDD tasks for a Sonnet 5.5 implementer)

Dependencies: Stage 3-5 Task 7 (scheduler job builders) and Task 4 (metrics) first; if they are not built, M0 builds only
the Task 7 scheduler part. Nothing here needs the YouTube ingest: the mentor can be built and used before the first real
ingest. Live use needs `qwen2.5:7b` pulled (templates work without it). New package `src/secondbrain/mentor/`.
Every task: failing tests first, run `.venv\Scripts\python -m pytest tests/<file> -v`, implement, run the whole suite,
ledger line in docs/ledger.md. No git commands.

M0. Scheduler builders (only if Stage 3-5 Task 7 is not done). Files: `bot/app.py`, `tests/test_bot_app.py`. As specified in
that plan. Acceptance: existing morning/evening tests green with the builders signature.

M1. Schema. Files: `schema.py`, `schemas/card.v1.json`, `tests/test_schema_mentor.py`.
Tests: new types validate; `MentorMeta` bounds (item 1-3, reason <= 300); a mentor card with `visibility="publishable"` is
rejected; old card JSON fixtures still load; regenerated schema file matches the model.
Acceptance: whole suite green, decisions.md line about the additive v1 change.

M2. Router task and temperature. Files: `llm.py`, `tests/test_llm_mentor.py`.
Change: `TASKS` gains `"mentor"` (default ollama); `OllamaProvider(..., temperature: float = 0)` and
`complete(prompt, *, system=None, temperature=None)`; triage/extract callers unchanged.
Tests: `route("mentor","private")` with a cloud provider raises `SensitivityError`; default temperature still 0 in the request
body; mentor override 0.7 appears in the body; `SB_ROUTE_SYNTHESIS=groq` does not affect the mentor route.

M3. Config and allowlist. Files: `mentor/config.py`, `tests/test_mentor_config.py`.
Tests: startup_finder path, a child of it, a parent of it, different case, and a `..` path resolving into it are all rejected;
non-git and missing paths dropped; missing file -> safe defaults; `money_cap_inr_per_week` default 0.

M4. Evidence. Files: `mentor/evidence.py`, `tests/test_evidence.py`.
`read_commits(repos, since, until, run) -> list[Commit]`; `level_for(item, commits, cards, proof_dir, cfg) -> (level, refs)`.
Tests (fake runner only): exact argv (contains `--no-pager`, `log`, no other subcommand) and env; timeout -> repo skipped;
hash given + in window -> verified; keyword match -> corroborated; outside mentor day (00:30 next day counts, 04:30 does not)
-> claimed; secret-looking subject hidden; SkipATS inbox parse with bad lines skipped and bounds enforced.

M5. Commitment parse, day clock, close-out. Files: `mentor/commit.py`, `mentor/day.py`, `tests/test_commit.py`.
Tests: numbered and bulleted input; more than 3 items trimmed; bet tags from hashtags and keywords; vague detection; mentor day
at 03:59 vs 04:00 IST; short grammar `1 done abc1234` / `2 missed got distracted`; auto-close at 03:59; `no_data` day from
`last_tick`; ids `mc_<YYYYMMDD>_<n>` stable on re-delivery of the same Telegram message.

M6. Facts and intents. Files: `mentor/facts.py`, `mentor/intents.py`, `tests/test_intents.py`.
Tests: table test of every row of 2.4 with the first-match order; FACTS never contain goals/profile text or thought/book card
text (marker strings); at most 15 lines; ids are real.

M7. Generation and guards. Files: `mentor/prompt.py`, `mentor/guards.py`, `mentor/templates.py`, `tests/test_guards.py`.
Persona loaded from docs/mentor-persona-prompt.md between the markers (missing file -> built-in short copy and a log warning).
Tests (fake provider): each guard rule 1-7 rejects a crafted reply; regenerate once then template; unknown id and invented
2-digit number rejected; anti-repetition with 14 stored messages; guard log has no message text; provider error -> template.

M8. Ladder and safety valve. Files: `mentor/ladder.py`, `mentor/safety.py`, `tests/test_ladder.py`.
Tests: levels 0-3 from fixture histories; no level 4, switch to `cut_scope`; de-escalation; rest and `no_data` days ignored;
keyword detection (case, punctuation) starts supportive mode and pauses penalties; crisis text produces the helpline message
exactly once and stops the mentor; `/back` resumes.

M9a. Bot routing and commands (no penalties). Files: `bot/app.py`, `bot/capture.py`, `tests/test_mentor_routing.py`.
- Routing precedence in `on_text`: (1) prefixed captures (`book:` ... `applied:`) as today; (2) a Telegram reply
  (`reply_to_message`) to a mentor message -> mentor handler; (3) `/commit`, `/close`, `/m` -> mentor; (4) everything else ->
  existing thought capture. No open "awaiting" window: plain text is never silently parsed as commitments or a close-out, so
  quick capture keeps working. If a plain message arrives while a morning question is unanswered and it looks like a list of
  1-3 outputs, the bot asks with buttons "Use as today's commitment? Yes / No" (No -> saved as a thought, as today).
- Commands: `/commit`, `/close`, `/m`, `/unwell`, `/back`, `/quiet`, `/restday`, `/answer`. All owner-only.
- Every model call runs via `asyncio.to_thread` (the Ollama client is synchronous), so a 30 s call never blocks polling or the
  scheduler. Close-out parsing and miss classification use temperature 0; only message phrasing uses 0.7.
- Tests: precedence table; reply-to routing; the Yes/No confirm; a 30 s fake model call does not block a second handler.

M9b. Bot jobs. Files: `bot/app.py`, `bot/brief.py`, `tests/test_mentor_jobs.py`.
- Morning brief gains the mentor part; midday job (3.3); `build_evening_checkin` replaced by the evening review behind
  `SB_MENTOR=on` (off -> today's behaviour byte-identical); daily cap across all unprompted jobs; quiet hours; catch-up
  message after downtime; `SB_MENTOR_SHADOW=on` records commitments but sends no nudges, ladder or penalties.
- Outbound filter (R7) test: goals.md and thought-card marker strings never appear in any sent text.
- Tests: cap of 4 with the priority order; quiet hours; mentor off = old behaviour; shadow mode sends only the morning
  question and evening close-out; review-delivered flag recorded for 3.4.

M10. Weekly review and context pack. Files: `mentor/weekly.py`, `bot/brief.py` (append to the Task 7 review), `cli.py`
(`sb mentor-pack`, `sb mentor-import`, `sb mentor-sample`), `tests/test_mentor_weekly.py`.
Tests: fixture week with exact numbers for every template line; questions chosen by priority; under 3 500 chars; pack refuses
without the flag; pack excludes `energy_health` reasons and money by default; import validates and drops unknown ids.

M11. Penalties (build only after 2 weeks of live use, see 9). Files: `mentor/penalties.py`, `bot/app.py`,
`tests/test_penalties.py`. Tests: menu validation (forbidden words, money over cap, 2-10 items); hash approval and invalidation
on edit; triggers a/b/c; caps 1/day and 2/week; severity order and round-robin; appeal once per week with the next-day
condition; skip and unserved never stack; supportive mode voids; replaying the ledger gives the same state; corrupt lines
skipped; `SB_MENTOR_PENALTIES` off -> no events.

M12. Docs and acceptance. RUNBOOK (commands, flags), NEXT_STEPS, decisions.md (schema change, experiment order).
Manual acceptance: one shadow day end to end in Telegram; kill Ollama mid-day and confirm templates; `/unwell` pauses;
SkipATS path in `profile/mentor.json` is rejected in the log.

Before the first real ingest: M0-M10 all. After: nothing in the mentor depends on it.

## 9. Critical review

Top 5 risks and weaknesses, worst first:

1. Building the mentor is itself the procrastination risk. The core system has not passed its own first test: no ingest, no
   live bot check, the 14-day stop-rule clock has not started. A 12-task mentor is about 2-4 days of build that could instead be
   job applications, and bet 1 (a remote infra job) is driven mostly by applications and interviews, not by a bot. Pushback: do
   not start the mentor before NEXT_STEPS A.5-A.7 are done, and cap the mentor build at the MVP below.
2. Self-refereed punishment has little force. He writes the menu, approves it, serves it on honour, and can stop the process.
   Penalties also add the most complexity (M11 is the largest task) and the most risk of making the bot something he mutes.
   The evidence ledger (a record he cannot argue with) is the part with real force. Delay penalties; build them only if
   2 weeks of ledger data show he keeps missing and still answers the bot.
3. A 7B local model will not "feel like a real mentor". It will sound like a sharp templated coach: repetitive at best, and
   wrong about him at worst. The design makes it safe (code-chosen intents, cited ids, guards, templates) but not wise. The real
   analysis is the weekly Claude session with the context pack. Set the expectation now so he does not judge the whole idea on
   the 7B's prose.
4. Nag fatigue and harshness. The anti-goal "a bot he ignores after two weeks" applies doubly to a strict one. The cap (4/day,
   merged with the brief), the ladder ceiling, the response-rate stop rule and the safety valve exist for this; if the response
   rate falls under 0.4 for a week, cut to evening plus weekly only.
5. Goodhart and privacy. Commit and application counts can be gamed with trivial commits and spray applications, and a strict
   mentor pushes toward exactly that. The mitigation (count only morning-committed items, show replies next to applications,
   human sample check) is partial. Separately, his feelings and excuses will sit on Telegram's servers; R7 limits what the bot
   echoes but cannot protect what he types. He should know this before he writes anything sensitive there.

Recommended MVP (build first: M1-M8, M9a, M9b, M10 minus the pack import; M8, the safety valve, ships before anything goes live):
- Morning commitment merged into the brief, evening close-out, evidence levels with the git allowlist, template plus 7B
  phrasing with guards, ladder levels 0-2, safety valve, weekly mentor section, context pack.
- Ship it in shadow mode for the 14-day brief clock, then live.

Delay (with the trigger to build it):
- Penalties (M11): after 2 live weeks, only if keep rate stays under 0.5 and the response rate stays at least 0.6.
- Midday nudge: after 2 live weeks, only if mornings without any log are common (3+ per week).
- Free `/m` chat beyond one follow-up: only if he uses `/m` at least 3 times a week; otherwise the 7B adds noise.
- `mentor-import` of Claude's reply: after he has done 2 manual deep reviews and finds them useful.
- SkipATS inbox: only after his explicit yes (vision doc), and only as the typed or self-produced file in 4.4.

Cut:
- Money penalties by default (cap starts at 0). A student whose goal is income should not pay for misses until he chooses to.
- Any "public" penalty that posts for him. The note goes into his private review; posting stays his manual choice.
