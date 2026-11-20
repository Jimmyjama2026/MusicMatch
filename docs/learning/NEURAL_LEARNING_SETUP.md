# Local neural learning setup

The [liked-song training update](FAVORITES_AS_TRAINING_YES.md) now counts current
favorites as positive judgments, including search-added songs without an anchor.
This supersedes the original exclusion of favorites alone described below.

The [genre input update](NEURAL_GENRE_INPUTS.md) supersedes the original audio-only
82-input architecture below: current shadow training uses 284 inputs, including
saved song/artist genre evidence, and 4,577 parameters. Readiness thresholds and
shadow-only behavior remain unchanged.

Implemented November 1, 2026. This is a shadow learning pilot: the existing
neighborhood recommender continues to rank suggestions. Neural checkpoints cannot
be promoted into live ranking by this implementation.

## Feedback and training

Schema 5 retains append-only vote events, reasons, timestamps and original song
and neighborhood context. Not my style, Wrong mood and Other are saved with No
votes and can supply negative training labels. Too slow and Too fast remain
directional neighborhood feedback; Already know it remains a familiarity exclusion.
These three reasons do not become generic neural dislikes. A/B choices are exported
separately for future preference learning. Earlier overwritten votes cannot be
recovered; retained earlier votes are backfilled on migration.

Training requires 100 usable, distinct judged songs, including at least 20 Yes,
20 No and three anchor artist families. Missing measurements or historical context
can make a judgment unusable. Favorites alone are not training judgments. A read-only
check during delivery found 21 usable Test judgments: 12 Yes and 9 No.

A small CPU model uses 82 numerical inputs, 16 hidden neurons and 1,345 parameters.
Inputs describe the candidate, its historical anchor and their differences. Artist
names, identifiers, feedback reasons and previous ranking scores are excluded.
Duration is excluded completely. Training uses class balancing, training-only
normalization and a chronological holdout with held-out song identities removed
from training anchor contexts. Evaluation compares the neural model with logistic
regression and the saved heuristic scores; small samples cannot establish quality.

After sufficient data, training runs in an isolated, hidden, lower-priority process
after 30 seconds of inactivity. Retraining requires ten additional eligible
judgments or ten changes to resolved judgments. Numerical libraries use one thread;
the parent terminates workers after ten seconds. Closing the application cancels
pending/running work. Test and Personal artifacts remain isolated. Checkpoints use
JSON and checked numeric arrays, retain at most two generations and enforce a
50 MiB model-artifact budget. Incomplete staging files are reclaimed. No new package,
GPU, paid service or model download is required. Synthetic subprocess training was
verified; the user's feedback has not been fitted below the readiness threshold.

## Matching and language

Duration's contribution to squared vector distance is reduced by 90%, from 0.3
to 0.03. The 200,000-song vector index was rebuilt locally in 6.557 seconds. Duration
stays in CSV metadata; other vector dimensions are unchanged. Known v1 feedback
snapshots with an identical catalog fingerprint can be reprojected for training;
unknown feature versions and incompatible checkpoints are rejected.

New suggestions and the active saved list require a high-confidence English title
estimate or an explicit backend English correction. Spanish, other languages and
unknown estimates are excluded. Title analysis cannot establish the language sung
in an audio recording and may exclude English songs with ambiguous titles. Language
diagnostics remain backend-only. Historical batches retain their original contents.

## Verification

The full suite passed 189 tests. Independent review covered data exports, model
inputs/evaluation, English filtering and application/worker integration. It prompted
fixes for baseline-score export, event ordering, class imbalance and staging cleanup.
The desktop preview used a cloned feedback database: five English-screened results,
two unfamiliar-artist slots, no warnings, and a maximum recommendation-phase UI timer
gap of about 38 ms. Layout screenshots were inspected. There were no song/data
downloads or CSV edits in this round. Changes have not been committed or pushed.
