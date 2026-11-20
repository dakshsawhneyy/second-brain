# Retrieval v2: measurements (numbers only, no note text)

Smoke test: 13 model-drafted questions over 37 cards (library too small for a real benchmark; drafted questions
paraphrase the note they came from). Add about 5 of your own questions later in profile/evals/questions.json.

| Step | Index | recall@5 | recall@10 | MRR | misses |
|---|---|---|---|---|---|
| Baseline (2026-11-20, before any change) | card-level, 1 vector per card | 0.62 | 0.69 | 0.59 | 4 of 13: all long notes (1.4k-2.2k chars) |

## Task 2: paragraph-level index (2026-11-20)

**Real library, smoke test (36 questions, 13 whole-note + 23 paragraph-level, both indexes limited to the sources an /ask pack uses):**

| Index | recall@5 | recall@10 | MRR | misses |
|---|---|---|---|---|
| old: one vector per card | 0.86 | 0.97 | 0.74 | 1 |
| new: one vector per paragraph | 0.86 | 0.94 | 0.71 | 2 |

Equal within noise (one question of 36). The library is 38 short notes, so there is little to gain in *finding* notes.

**Synthetic long journals (8 notes x 6 paragraphs, real embedding model, 16 questions about late paragraphs):**

| | finds the right note (recall@5) | top result SHOWS the paragraph that answers it |
|---|---|---|
| old | 1.00 | 0 / 16 (it always showed paragraph 1) |
| new | 1.00 | 13 / 16 |

The gain is in what reaches Claude, not in which note is found.

**Scale (slow test, 200,000 chunks x 768 dimensions):** warm query median 166 ms (max 210 ms); first query after start 1.2 s (loads the matrix). The first attempt with a float16 cache measured 328 ms (> 300 ms target), so the cache is float32 up to 1.2 GB (about 390k chunks) and float16 above that.

## Task 3: the /ask pack (2026-11-20)

**Bug found by measuring the real pack:** with real data the whole "older entries that match the question" section was cut
off the END of the pack (one 7,000-char cap on the whole text; the matches were the last section). `/ask` never saw the notes
that search found. Now every section has its own budget (goals 900, profile 2,500, earlier conversation 1,000, recent 1,300,
evidence 2,800; total cap 9,000) and the evidence is present: real pack 7,853 chars, all five sections present.
Also: the profile now reaches Claude up to 2,500 chars (it was cut to 1,800), a coverage line says how many notes and which
dates the evidence covers, the prompt tells Claude to say what the evidence does not cover, notes are indexed the moment they are
saved, and a free local re-phrasing runs only when the first search is weak.

## Independent review (2026-11-20) and its fixes
A read-only reviewer found 1 Critical and 6 Important problems; all were fixed test-first (see tests/test_review_fixes.py):
C1 a deleted-and-rebuilt index could leave the bot's cache pointing at the wrong rows (a /private note could be returned);
I1 keyword shortlist cut before the private/source filters; I2 no keyword fallback while the index is missing; I3 one failing day blocked all
later digests; I4 a digest kept text of removed/private notes; I5 the living profile would have switched itself on; I6 a rebuild embedded while
holding the write lock. Final scale numbers (200k chunks): unfiltered warm 153 ms, filtered as /ask searches 257 ms (the first filter version used
table joins and measured 649 ms; the filter columns now live inside the keyword table, schema 3).
