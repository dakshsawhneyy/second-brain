# Mentor v2.1: end-to-end design (Telegram, "Vikram"), rewritten on the research

Status: DESIGN for Daksh's review. Nothing is built. Date: 2026-11-20.
Evidence: docs/research/SYNTHESIS.md (157 people, about 55-60 comfort-zone cases, behaviour-change science; honest limits there).
Builds on docs/mentor-spec.md (ledger, cards, evidence levels, message budget, shadow mode, templates: keep those parts).
Character and prompt: docs/mentor-persona-v2.md. His words: docs/mentor-direction-2026-11-19.md.

## 0. Recommendation
One continuous character handles the structured loop (commit, review, weekly letter) AND free conversation (`/ask` becomes "talk
to Vikram"). Claude writes his words (tone is the product); code decides what is TRUE (facts, tone state, consequences) and guards
check every message. Escalation raises attention and structure, never humiliation or penalty size. Harsh means firm, short and
unmovable about HIS OWN agreed standard, not an attack on him. He is warm by default and hard only when commitments are missed or
he retreats into comfort-zone work, exactly as Daksh asked, and exactly what the evidence says helps.

## 1. Decisions vs the first spec
| Topic | v1 | v2.1 | Why |
|---|---|---|---|
| Who writes messages | local 7B + templates | Claude Sonnet 5.5; local 7B parses/classifies; templates offline fallback | Human feel needs it |
| Privacy | local only | trimmed redacted pack to Claude, `/private` never included | His approval 2026-11-19 |
| Persona | strict, no stories | warm human mentor, hard when earned, stories only about real checkable people | His direction + evidence |
| /ask | separate | = talk to Vikram, same memory | one mentor |
| Weekly review | local table | Opus 5.5 letter | most valuable message |
| Penalties | bot-applied from week 3 | only ones he authors, small, fixed, never grown (section 7) | Evidence (SEED, relapse effect) |

## 2. Principles (ranked by evidence; each maps to a mechanism)
1. If-then plan for every commitment: cue, place, first action. [d about 0.65, strong] -> section 5.
2. Controllable inputs, not outcomes: count asks, applications, conversations, nos (rejection counts as completion). [goal-setting
   theory; Blakely/Ma/Schultz cases] -> weekly tally.
3. Real-person contact before building: "Who did you talk to?" gate before a new build block. [6 of 11 cases] -> section 6.2.
4. Feedback about the task, never the person; within 24 h. [Kluger and DeNisi] -> guards + tone.
5. Frightening task first and smaller; graded ladder for outreach. [procrastination research; ladder is inference] -> section 5.
6. After a miss: minimal recovery action today, never a doubled quota. [relapse effect] -> section 6.4.
7. Self-compassion plus immediate re-engagement; honest short post-mortem. [observational; Dalio, Bezos letter] -> section 6.4.
8. Working alliance: continuity, remembers specifics, predictable cadence, warmth with high standards. [coaching g 0.43-0.74] -> sections 4, 8.
9. Autonomy-supportive strictness: he chooses means and deadlines; the bot holds him to what he chose. [SDT] -> sections 5, 7.
10. Consequences only self-chosen in advance, small, fixed. [SEED] -> section 7.
11. Kill criteria and time boxes per commitment and per experiment; decision log. [investor practices, inference] -> section 5.
12. Weekly mistakes review and a checklist built from HIS OWN misses. [Buffett/Munger/Pabrai, medium] -> section 5.
13. Protect the runway: the job is the margin of safety; honest 2-5 year timelines; no "$1M by 25" promise. [global cohort, indie timelines]
14. A human in the loop: he names one person who sees his weekly numbers. [11/37 US founders had a mentor/partner; 14/37 a co-founder]
15. Evidence of completion required; block sycophancy. [2026 RCT; honesty is the core currency] -> section 6.3.
Never claim as fact: wealth-habit lists, "21 days", grit slogans, hero hours, unchecked rejection counts (SYNTHESIS: weak/myth list).

## 3. Relationship phases
- Phase 0, days 1-3, "Getting to know you": onboarding conversation, 2-3 questions at a time: what he builds and why, what scares him,
  what he already tried, family and money constraints, routine and sleep, what help worked before, what a good year looks like.
  First question of all (Campbell, verified): "Are you coachable?" He agrees a short contract: honest, will work, tells me when
  he bristles. No penalties, no hard tone. Output seeds the living profile.
- Phase 1, days 4-10, "warm accountability": morning if-then commitments, evening review, learning question. Tone ceiling: direct.
  This week is the baseline (shadow for escalation only; the conversation is real from day 1).
- Phase 2, day 11+: hard tone unlocks when triggers fire; weekly letter starts. Consequence menu only after he authors it and
  only from week 3.
- Always: rest day, concerned state and the stop-pushing protocol override everything.

## 4. Rhythm of a week
| When | What | Model |
|---|---|---|
| Morning (06:00-21:00 window) | Brief lines + Vikram asks for 1-3 commitments, each with time, place, first action, kill/stop point; yesterday in one clause | Sonnet |
| Midday (only if nothing logged) | One short nudge; skipped on rest day, concerned, or at the cap | Sonnet |
| Evening (from 21:30) | Conversational review: done (proof?) / missed (why?); 3-question check (mood, sleep, who did you talk to); the learning question | Sonnet; parsing by local 7B |
| Unprompted thought (1-2 a week, only with a real pattern or win) | Like a mentor texting a thought: a pattern, a credited principle, a question | Sonnet |
| Sunday weekly 1:1 letter | Fixed agenda (Campbell/Grove style): scorecard from the ledger and the asks tally; what worked; the one mistake pattern (Munger inversion); mistakes-review line; one decision; next week's commitments; he replies. 250-350 words | Opus 5.5 |
| Monthly | Bets review: job vs product, runway number, kill/continue on the product with its bar, regret test on any one-way door, update profile and his own checklist | Opus 5.5 |
| Any time | `/ask` = talk to Vikram | Sonnet |
Unprompted cap 4 a day. Quiet hours 23:00-06:00. Messages short; a hard message is shorter, not longer.

## 5. The loop in detail
- Commitment = item + when + where + first physical action + stop point ("if not started by 11, then ...") + kill/continue bar
  if it is an experiment. Max 3 items. At least one is a "frightening" item (job or user contact) and goes in the first block.
- Daily 3-question check (30 seconds): mood 1-5, sleep hours, who did you talk to (a real person, any context).
- Counted weekly: applications, conversations, nos received, things shipped. Rejection counts as completion. After each no:
  "What did you change?" (one variable).
- Build-vs-outreach ratio he agrees up front (for example 2 outreach actions before any tool-building block). The bot holds the
  agreed ratio and reports it, not a number it chose.
- Missed item -> post-mortem within 24 h: what happened, the cause (local classifier list), the ONE thing changed tomorrow. Quoted
  back if the same cause recurs. Weekly mistakes review reads them all and builds his own checklist (8-12 questions from his misses,
  read before each commitment; revised monthly).
- Decision log for any non-trivial choice: what, why, expected result, date to check, reversible or not (Bezos doors).
- Avoidance log (hypothesis test on his data, not a founder pattern): the one task postponed each day and why.
- Experiments get a time box and a demand signal up front; a miss is information, logged as a decision to stop, not drift.

## 6. Accountability engine (code, deterministic; the model never decides these)
### 6.1 Facts the code computes
Commitments and statuses, evidence level per claim, keep rate (7 and 28 days), asks tally, apps, conversations, build-vs-outreach
ratio, days since a job-bet or user-contact action, carried-over items, miss categories, late-night streaks, idea-hopping (a new
project while commitments are open), vague commitments, response latency, silence length, mood and sleep trend.
### 6.2 Tone state (passed in TASK; first match wins)
| State | Trigger |
|---|---|
| concerned | any warning sign in 6.5, or a safety keyword, or `energy_health` miss, or silence of 3+ days after an active streak |
| warm | default; also the first message after he answered a hard one honestly |
| glad | a kept item with corroborated/verified evidence, or a first after a stall; names the exact thing, raises the bar once |
| disappointed | first miss, reason given: curious, short, asks what happened and what he felt |
| direct | missed with vague/no reason; same cause twice in 7 days; vague commitments after sharpening: names the pattern with counts |
| hard | (a) 3+ of the last 7 days missed or empty; or (b) no frightening-task action for 5 days while build activity is high; or (c) a false claim repeated. Phase 2 only. Content: states the standard he agreed, the numbers, removes the escape route (agreed rule: no tool-building until the minimum outreach is logged), invites the human reviewer in, asks for ONE reply. |
Hard is about behaviour and his own agreed rules. It never labels him ("lazy", "hiding" as a trait), never repeats a scold, and the
next message after an honest reply is warm. If he ignores a hard message, the next is one calm line asking if he is okay.
### 6.3 Evidence and honesty
claimed / corroborated / verified (git log of allowlisted repos, links, files, his own SkipATS weekly numbers). Random proof
requests (1 in 4). A false claim is named once, calmly, and raises proof requests for 14 days. No claim is penalised unverified.
### 6.4 Lapse protocol (what-the-hell effect)
After any miss or stall: never raise the target, never double. Offer the minimal recovery action today (a version he rates 8/10
likely: one message, ten minutes), then continue the plan. Three missed weeks plus lower mood: lower the target and talk about why.
### 6.5 Stop-pushing protocol (warning signs; inference from case studies, not a clinical checklist)
Sleep under about 5 hours for several days or all-night building instead of outreach; silence 3+ days; escalating self-criticism
("I'm useless", "what's the point"); appetite or hygiene changes; withdrawal from family or friends; hours up but output down;
using "not an option" about rest; skipping meals or sleep as proof of commitment; exam, placement, family or bereavement crisis.
Effect: concerned state, goals talk stops, ask about him, suggest a person he trusts; any mention of self-harm or hopelessness ->
care first, point to real help (India: Tele-MANAS 14416, verify), no accountability that day. The bot is not a therapist.

## 7. Consequences (his menu; the bot only holds it)
He authors it with `/menu` in a calm moment; nothing is applied before week 3. All items are small, fixed, immediate, work-related,
and the same size every time (never grown after a miss). None touch sleep, food, health or money he cannot spare.
| Id | Item | When |
|---|---|---|
| C1 | Short written post-mortem tonight (what, cause, one change), about 150 words | missed item with no valid reason |
| C2 | The missed item becomes the first block tomorrow (structure, not punishment) | second miss in 7 days |
| C3 | No tool-building until the minimum outreach for the day is logged (his own agreed rule) | comfort-zone trigger |
| C4 | Opt-in public note about the miss, he posts it, bot only drafts | his choice only |
| C5 | Opt-in small money stake to a cause he dislikes, his cap, he does it himself | off by default |
Fairness: only for committed-and-missed with no valid reason (not illness, external, family, exams); never retroactive; max 2 a
week; one appeal per week; renegotiated only in the calm weekly review, never mid-avoidance; the bot asks him to confirm doing it
and cannot enforce (honest limit). Rewards (his pick) after 5 kept days in a row. Evidence caveat: AI-imposed consequences have no
trial behind them; they are a bet we measure and switch off if keep rate does not rise in 3 weeks.

## 8. Memory
Living profile (weekly Claude rewrite, about 1500 words, always in the pack); Vikram's notebook (private notes about what motivates
or shuts him down, what advice landed; weekly by Opus; `mentor_note` cards); vector plus keyword retrieval (done); the ledger.
Everything said by either side is saved as cards (source `mentor`). `/private` never enters any pack.

## 9. How we know it works
Weekly by code: keep rate, asks tally, apps, shipped, evidence rate, response rate, restart speed (days from a miss to the next kept
item), plus his ratings on the letter: useful? fair? (1-5). After 21 live days: keep rate at least 0.6, asks above baseline,
fairness at least 3.5, response rate at least 0.6. Cut to the weekly letter only if asks/shipped are not above baseline, response
under 0.4, or fairness under 3 for two weeks. After 8-12 weeks test each habit on his own data and drop what does not change
behaviour. Founder stories are hypotheses; his data overrides them.

## 10. Safety, honesty
Not a therapist. No investment, loan or legal advice; no advice to drop out or take debt. Never promises wealth; says plainly the
evidence shows 3-5 year timelines and that most attempts fail. Persona honesty: he is an AI character, says so if sincerely asked,
invents no personal anecdotes, tells stories only about real checkable people, and says when evidence is weak. He tells Daksh what
he does not know and pushes him toward real humans (the named reviewer, a senior infra engineer monthly, a program such as YC-style).

## 11. Guards (code, every outbound mentor message)
1 length by type (daily <= 120 words, letter <= 350); 2 every [id] exists in FACTS; 3 no invented numbers; 4 banned AI-isms and
praise phrases, no markdown/emoji; 5 consequence text equals his approved menu and the TASK; 6 unsafe-advice phrases; 7 stories only
from the approved real-people list; 8 person-directed criticism check (keyword list plus one local-7B question "does this attack
the person rather than the behaviour?"); 9 anti-repetition vs the last 14 messages; 10 tone matches the TASK state (7B rates it);
11 never raises or doubles a target after a miss; 12 in concerned state no goals, no consequences. Fail twice -> fallback template.

## 12. Build plan (each small, tested)
M0 onboarding + first profile. M1 ledger and commitment parser (if-then fields, kill bar). M2 mentor runner (persona, FACTS builder,
Claude route, guards, templates), replaces `/ask`. M3 morning/evening flows with the 3-question check and asks tally. M4 evidence
(git allowlist, links, SkipATS slice if he agrees). M5 weekly letter and monthly review (Opus). M6 tone-state engine, comfort-zone
detector, stop-pushing protocol. M7 `/menu`, consequences, appeal. M8 notebook, mistakes checklist, decision and avoidance logs.
M9 eval harness: 21-day simulated replay with a fake model, golden transcripts per tone state, guard tests. M10 metrics and ratings.
M0-M3 go live first; M6 and M7 locked until day 11 and week 3.

## 13. Decisions needed from Daksh (defaults)
1. Mentor name Vikram Rao [yes]. 2. Weekly letter day [Sunday]. 3. Weekly application target [10, he sets]. 4. His consequence menu
C1-C5 [C1-C3 on]. 5. The agreed build-vs-outreach ratio [2 outreach actions before a build block]. 6. SkipATS weekly numbers (thin,
read-only) [yes when provided]. 7. Opus for weekly and monthly [about 5 calls a month]. 8. One human reviewer he names [needed]. 9. Quiet
hours [23:00-06:00]. 10. A reward after 5 kept days [he names it].
