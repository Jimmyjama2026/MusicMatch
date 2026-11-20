# Backfill after title screening

The user reported no more suggestions after an extended rating session. Read-only
reproduction on the active Test profile confirmed a retrieval bug: Fresh mode's
five-result request returned zero, while a wider request with identical likes and
exclusions returned 16. The 200,000-song catalog had not been exhausted.

The rich engine first retrieved bounded per-neighborhood queues and then applied
the title-language predicate. When that predicate rejected the shortlist, it did
not inspect remaining ranked, genre-eligible rows. Fresh exclusions progressively
removed accepted titles, exposing this failure. Short/ambiguous or low-confidence
titles are often rejected by the existing English-title policy, including titles
that could belong to English songs. This screening still cannot verify sung language.

`neighborhoods.recommend` now backfills an undersized filtered pool from remaining
ranked eligible rows, retaining exact scores and applying the same predicate. Each
candidate is checked at most once within that recommendation call. It stops when
there are enough accepted candidates for selection (at least ten when available),
or when the eligible ordered rows are exhausted. This can require more screening
than before; the desktop's existing worker and language cache handle the work.

Genre constraints, rating/favorite exclusions, Fresh exclusions, diversity, unknown
genre handling and English-title requirements are unchanged. No database schema,
saved recommendation batch or personal feedback was modified by diagnosis.

Read-only validation with the same active profile:

| Request | Before | After |
|---|---:|---:|
| Five suggestions, Fresh off | 5 | 5 |
| Five suggestions, Fresh on | 0 | 5 |

At diagnosis, neural eligibility was **69 distinct usable judgments: 25 Yes and
44 No, across 19 anchor artist families**. Thus 31 additional usable distinct
judgments are required for the existing 100-judgment minimum. The binary-class and
artist-family minima are already met. There was no saved training status artifact;
the model is still in shadow mode and is not the cause of this retrieval failure.

The regression test rejects an entire initial shortlist and verifies that lower-ranked
accepted catalog songs still fill the batch. All 201 tests passed. Reproduce local
read-only checks with `scripts/diagnose_recommendations.py`; `--wide` also tests a
200-result request. Aggregate diagnostics are saved under ignored
`data/sources/recommendation_diagnostics/`. The diagnostic uses a memory-only language
screen and therefore does not apply saved per-track language corrections; this
profile's reproduced failure was resolved with the stricter default screen.
