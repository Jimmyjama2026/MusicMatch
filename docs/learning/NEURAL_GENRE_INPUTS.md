# Genre-aware shadow training

The user requested genre inputs for the neural learner. This update uses the
existing local artist fallback and any already saved recording labels. It does not
collect additional song labels, call Last.fm or change live genre eligibility.

## Inputs and provenance

The model now receives 284 numerical inputs:

- The previous 82 measured audio/context inputs, still excluding duration.
- 64 deterministic binary genre-hash coordinates for the candidate, 64 for the
  historical matched anchor, and 64 for their shared genre labels.
- Ten explicit values describing known/unknown genres, overlap, Jaccard similarity,
  known incompatibility, and whether each side uses recording or artist evidence.

Recording labels take priority over artist genres. Unknown is distinct from a
known conflict. Genre text is normalized using the existing matching policy;
there is no newly inferred hierarchy. SHA-256 bucket assignment is fixed before
any training/evaluation split and fits no vocabulary on evaluation data. Hash
collisions are possible: this is a compact initial encoding, not a unique coordinate
for every genre. Live genre gates continue using exact labels, not these hashes.

Candidate IDs, titles, artist names, ranking outputs, feedback reasons and outcomes
do not become predictor inputs. A Yes/No choice supplies the training target only.
Existing audio eligibility, per-profile isolation, balancing, held-out identity
protection and training-only normalization remain in place.

## Saved judgments

`comparisons.snapshot` previously discarded genre evidence. It now preserves deep
copies of `genre_evidence` and `artist_genre_evidence` for candidates, anchors and
comparison records. The feedback export therefore retains the genre context already
saved in recommendation batches.

Historical ratings missing genre evidence remain usable with explicit unknown
features. The export does not look up current genres and rewrite old context. A
read-only check found **13 usable Test records, 12 with saved genre evidence on
both candidate and anchor**. No personal feedback or historical batch was changed.

## Training and compatibility

The hidden layer remains 16 neurons; the expanded network has **4,577 parameters**.
The model version is `contextual-shadow-mlp-v2-genres`. Artifact metadata includes
the exact genre feature contract and input width; old audio-only checkpoints and
altered genre contracts are rejected by the scorer. The training manager includes
the model version in attempt fingerprints so a ready profile can retrain after an
input-schema update without requiring ten more votes first.

Readiness still requires 100 usable distinct judgments, at least 20 Yes and 20 No,
and three anchor artist families. The chronological training/evaluation split also
needs both classes. Status counts now report how many records have known genres on
both sides; worker reports also include candidate and anchor genre coverage.

This remains **shadow training only**. It cannot automatically take control of live
ranking or override genre gates. More inputs do not establish better recommendations;
the larger model may overfit small samples and needs evaluation against the existing
baselines. A/B judgments and directional/familiarity reasons retain their separate
policies and are not silently turned into binary neural labels.

## Validation

Tests cover genre-driven distinctions with identical audio, explicit unknown versus
known mismatch, recording-over-artist priority, source indicators, predictor invariance
to song/artist identities and outcome fields, frozen feedback export, NumPy/scikit-learn
prediction parity, and rejection of incompatible genre artifacts. A synthetic model
learned the genre-only signal; this is a wiring check, not measured user preference
accuracy. The complete suite passed 200 tests.
