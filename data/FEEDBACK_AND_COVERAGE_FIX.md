# Rating scroll position, taste coverage and directional feedback

Implemented locally on October 31, 2026. No commit, push, dependency download or
test write to the user's feedback database was performed.

## What was wrong

Yes/No saves replaced the entire QVariant list driving recommendation cards.
Qt rebuilt the list and reset its viewport. Current and historical recommendation
views now use stable `QAbstractListModel` instances. Rating changes update only
the affected rows; history-filter removals remove rows without resetting the rest.
Changing the actual batch/profile can still reset the list deliberately.

The existing selector balanced numerical neighborhoods, but several neighborhoods
could all belong to one liked artist. Its two discovery slots could also both
follow one other artist's anchors. Many likes from Morgan Wallen/Luke Combs could
therefore occupy the same small batch alongside discoveries tied to Adele, while
older liked artists were omitted.

The selector now considers actual matched-anchor artist credits/IDs across both
ordinary and discovery picks. It avoids repeating an anchor family while close,
eligible alternatives exist; the two discoveries prefer different anchor families
when possible. Coverage requires existing shared-feature distance <=.10, and it
relaxes for focused requests or insufficient alternatives. This is artist-anchor
coverage, not verified genre balancing. Five slots still cannot represent every
liked artist in every batch. Artist bonus stays .18; discoveries retain their
unfamiliar-artist and acoustic suitability requirements.

## What feedback actually does

Before this fix, **Too slow / Too fast were recorded but ranked like generic No**.
They did not learn opposite tempo preferences. They now penalize the appropriate
tempo side locally, scoped to the saved matched anchor (or rejected-song features
when the anchor snapshot is unavailable). Too slow favors moving faster relative
to the rejected recording; Too fast favors moving slower. Invalid/missing tempo
is not invented, and unsupported feedback falls back to the generic No behavior.
Generic and directional dislike effects share one maximum .04 penalty, rather
than accumulating without a bound.

Existing behavior remains: Yes supplies a positive anchor; No excludes the
rejected recording/aliases and penalizes similar candidates; Already know it is
an exclusion without a taste penalty on the rich path; A/B comparisons make a
bounded local adjustment without turning the loser into a dislike. Feedback
affects new requests, not the order of a saved batch being rated.

These are bounded feedback rules. The app does **not** train a neural network or
learn general feature weights from every vote. Tempo is recorded BPM, which can
use half/double-time conventions and does not capture every perception of pace.
Vocal delivery and instrumentation are still not measured directly.

## Verification and limitations

- Full suite: **159 tests pass**. Nine Qt checks include a scrolled card receiving
  Yes, No and Yes again, verifying saved choices, no model reset and unchanged
  scroll position. Independent review repeated the Qt suite.
- Seven new ranking checks cover opposite tempo feedback, unrelated-neighborhood
  isolation, missing/invalid tempo, combined penalty caps, many same-artist groups,
  discovery-family variety and focused/unsuitable-alternative fallback.
- Independent review found and repaired an invalid-candidate-tempo edge case;
  no remaining blockers were found in the UI or ranking changes.
- `scripts/audit_feedback_changes.py` replayed a fixed read-only snapshot of the
  active Test profile: 32 favorites, 15 latest ratings, no A/B records. With the
  new coverage policy disabled and tempo reasons treated as generic No, the five
  results followed four distinct anchor credits. Enabling coverage produced five:
  Tate McRae, Morgan Wallen, NF, Luke Combs and Adele. One repeated Morgan-anchored
  pick was replaced by an NF-anchored pick; both discovery slots remained filled.
- Enabling directional feedback did not further change that particular top five;
  its directional increment was zero there because of local scope/other dislike
  penalties. This does not establish taste-quality improvement. Regression tests
  establish that the directions differ on applicable candidates.

Audit output stays under ignored `data/sources/feedback_fix_audit.json`. The replay
emulates prior rules through explicit ablation settings, not an archived executable;
cache warmth differs, so its timings are not a performance comparison. Restart
the app and generate a new batch to use the changes. Existing history stays frozen.
