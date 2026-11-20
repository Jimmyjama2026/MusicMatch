# Title screening, request steering and A/B feedback

Approved implementation, October 31, 2026. Changes remain local and unpushed.

## Use the new controls

Restart `python main.py` and generate a new batch. New suggestions are screened
using their written titles. Under **Why this match?**, choose **Same feel**,
**Slightly slower**, **Slightly faster**, **More energetic**, or **Less artist
influence**, then press **More like this**. Steering affects that request only;
the next ordinary request uses neutral settings. Saved history displays the
steering option and target without replacing the song's measured features.

Expand **Compare two songs (optional)** when a suitable pair is available. Choose
A, B, About equal or Skip only if you know both songs. Undo reverses the latest
choice. Reset comparisons requires confirmation and clears only this profile's
comparisons, preserving favorites and Yes/No ratings.

## Title-language policy

`py3langid==0.4.0` runs locally, with every supported language enabled. No titles
are sent to an API. English/Spanish classifications remain eligible; confident
other-language classifications are screened out. Ambiguous, numeric and short
Latin-script titles remain eligible as **Unknown**. Missing detector access
remains visibly Unknown, rather than pretending the language is English. Cache
failures fall back to in-memory screening.

A real-data preview found that four-character Chinese titles were too short to
classify. The reviewed v2 policy therefore also recognizes clearly non-Latin
written titles: at least two non-Latin alphabetic characters comprising at least
25% of all title letters. It reports `other` and an explicit script-evidence
reason, with no invented model confidence. Normalization preserves Spanish
diacritics and avoids treating isolated mathematical symbols as foreign text.
The policy version invalidates old cached classifications.

This is **title-language screening, not sung-language verification**. English
titles on non-English recordings can pass, and mixed or stylized titles can need
correction. Language labels and correction controls are backend-only at the
user's request. The backend supports automatic detection, English, Spanish,
Other or Unknown overrides. Corrections apply to
that track across profiles and future requests; old saved explanations stay
unchanged. Overrides take priority over both detector and script checks.

Screening runs on retained candidates before final selection and the two
unfamiliar-artist slots. It does not scan 200,000 titles during startup. A bounded
candidate pool can still produce a discovery shortfall; no claim is made that
all eligible tracks in the catalog have been exhausted.

## How steering and comparisons affect ranking

Tempo targets move 10% slower/faster; energy targets increase by .10, capped at
1. Target-feature closeness changes scores by at most .025. Less artist influence
halves the .18 artist bonus for this request. The original vectors, measured
anchor distance, groups and discovery suitability gate remain intact. Unsupported
features are explicitly labelled as unapplied.

Each new batch can offer one pair with the same actual anchor and comparably
ranked candidates. Pair identities ignore left/right order and recording aliases;
seen pairs are not repeatedly offered. Left/right order alternates between
offers. Some batches have no suitable pair, especially when each suggestion uses
a different anchor; focused More like this requests often provide one.

Choices are stored separately from binary ratings in schema version 4. Up to 32
latest valid unique comparisons apply a mean local similarity adjustment capped
at .02, only within .10 of the saved anchor. The losing song is not disliked or
excluded. Equal and Skip have no directional ranking influence. Incompatible
feature/catalog snapshots are ignored. This is a bounded heuristic, not a trained
neural network. Historical results remain frozen; feedback affects new requests.

## Verification and review

Independent step reviews checked title screening, ranking, persistence and UI,
followed by a separate integration review. Findings repaired before delivery:

- Per-title SQLite transactions made 1,000-title screening take 11.64 seconds.
  A batched session reduced the original-policy check to .719 seconds cold and
  .0063 seconds warm. These timings are not accuracy measurements.
- Real-data visuals exposed short non-Latin titles slipping through Unknown;
  the v2 written-script safeguard and regressions address this.
- Repeated comparison distance calculations made 32 active pairs take 1.08–1.11
  seconds. Shared seeds now take .443–.471 seconds in the same warm catalog check,
  with numerical parity tested against the original formula.

The full suite passes **151 tests**. Eleven language tests were independently
repeated after the script-policy change; eight actual offscreen Qt workflow
checks pass at 100%, 150% and 200% scaling. Tests cover schema migration, profile
ownership, undo/reset, equal/skip, immutable history, neutral parity, directional
steering, bounded comparison influence, filtering before discovery and cache
failure behavior. `pip check` reports no broken requirements.

Real-profile visual QA used a disposable SQLite backup. The final focused/faster
preview returned five suggestions, two discovery slots and a real comparison,
with no Qt warnings. Cold end-to-end recommendation took about 1.41 seconds;
the longest recommendation-phase timer gap was about 39 ms. Startup took about
10.3 seconds under concurrent test load. These are offscreen smoke checks, not
physical-monitor frame-rate certification. Screenshots/timings are in ignored
`data/sources/steering_preview/`.

## Storage and dependencies

The detector wheel is 4,600,605 bytes; installed payload is 4,643,804 bytes.
Combined retained wheel/package storage is about 9.25 MB. The title cache is
capped at 40 MiB, leaving room for its rollback journal within the 100 MB
additional language-component disk budget. It lives under ignored `data/sources/`.
There are no subscriptions, bulk music/lyrics/audio downloads or cloud uploads.
Future comparison history adds small per-pair snapshots to the existing local
feedback database; snapshots exclude recursive maps and explanations.

Primary package source: [py3langid](https://pypi.org/project/py3langid/0.4.0/).
