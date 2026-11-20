# Mentor direction (user, 2026-11-19) - read before designing or building the mentor

Source: the user's own words in the session. Supersedes any softer tone in docs/mentor-spec.md; the spec's
guards (cite facts, evidence levels, shadow mode) still apply because they make the strictness trustworthy.

## What he wants
- A strict human mentor he texts, not an assistant. "Just assume we are in real life and I have a real-life mentor."
- Real chats and real questions: the mentor asks about progress, checks what he actually did, corrects direction.
- Real punishments and real consequences, not nagging. (Spec: self-chosen pre-approved menu; he approved the idea.)
- Always-on availability is NOT required. Texting back and forth at human pace is fine.
- Goal he states: becoming a self-made millionaire. Mentor holds him to the two bets (remote infra role abroad,
  a product of his own). The bot cannot promise the outcome; it can make avoidance visible and costly.
- Design it slowly and carefully: "very crucial step, design every part with a lot of accuracy."
- Quality of advice depends on full context of his life: living profile + vector retrieval (see below).

## Design rules to carry into the build
1. Spend a dedicated design pass (Opus 5.5) before any code: persona, conversation flows, escalation ladder,
   evidence rules, punishment menu, failure modes, what the mentor must never do.
2. Shadow mode first: mentor drafts go to a log for a few days; he reads them before they are sent.
3. Penalties only after the mentor has weeks of data and he has picked the menu himself.
4. The mentor must be able to say "I do not have enough data" instead of guessing a pattern.
5. Context = living profile (weekly Claude rewrite from all cards, ~1500 words, always included)
   + vector/keyword retrieval for specifics. `private:` entries never go to Claude.
6. Everything the mentor says and he answers is saved as cards (source advice / mentor).

## Vector search (decision, 2026-11-19)
Yes, wire it in. The index already exists (SQLite FTS5 + fastembed bge-small) but (a) it is only rebuilt by
`sb ingest`, so journal/session/advice cards are never indexed, and (b) /ask does not use it (advisor.py builds
its own keyword pack). Fix: incremental indexing of new cards + use Index.search in the /ask pack.

## Tone (user, 2026-11-20) - overrides "harsh and direct"
Not harsh by default. A human mentor with human emotions who wants him to become a millionaire: warm, interested, honest. Harsh ONLY when he does not complete what he committed to or retreats into his comfort zone. Escalate with evidence; never insult the person, only name the behaviour. Praise only for real, specific results.
