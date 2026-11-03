# Modern desktop delivery — October 31, 2026

Approved scope implemented locally; no commit or push was made.

## Interface and application

The default `main.py` launcher opens a Qt Quick desktop with charcoal backgrounds
and dark royal-blue controls. Separate Discover, Liked songs and History views,
responsive layouts, virtualized lists, keyboard search, reduced motion, profile
isolation and explicit Test-reset confirmation replace the earlier scrolling Tk
window. `main.py --legacy` keeps that window available.

`application.py` holds UI-independent actions. `desktop_qt.py` serializes service
and SQLite work on one worker and delivers snapshots to the main thread. Saved
history keeps its original favorites; viewing/rating history does not replace
current favorites. More like this focuses on one liked song, preserves the full
liked list and excludes songs already liked. Failures are visible with retry.

## Recommendations

The shared-artist adjustment decreased from .20 to .18; other weights remain
unchanged. Canonical identities, one shared selector and immutable versioned
configuration replace duplicated ranking rules. Candidate retrieval preserves
artist diversity and includes only conservatively matched graph recordings with
actual audio features. Each receives the same acoustic scoring before bounded
listening support. No unknown audio features are invented.

The James Arthur/Olivia Rodrigo example still reproduces distance .035426761955
without an artist bonus. This is a development regression, not proof of overall
quality. No neural network is trained: the active Test profile has seven Yes
judgments and no taste-No judgments. The 200,000-song CSV and saved 21-dimensional
vectors remain the audio catalog. No new bulk music, lyrics or audio was downloaded.
See [ranking evidence and limitations](RANKING_REFACTOR_REPORT.md).

## Validation and performance

- Full suite: 106 tests passed, including service/history persistence, ranking,
  exclusions, graph unions, and real offscreen Qt interactions.
- Qt workflow checks passed at 100%, 150% and 200% scaling; wide and narrow actual
  data renders were inspected. Physical-monitor frame rate remains unverified.
- Frozen Test inputs reproduce the exact same ten IDs and scores before/after
  performance optimization. Independent replay took 242 ms; repeated warm
  requests ranged roughly 0.20–0.26 seconds. These timings do not prove quality.
- Latest offscreen five-result end-to-end request took 295 ms; the longest event
  loop timer gap during that request was 27 ms. Startup took 6.22 seconds with a
  233 ms maximum timer gap. Chunking catalog JSON conversion reduced the previous
  startup gap of 1.2 seconds; startup is not yet entirely hitch-free.
- Preview runs used a disposable backup of the personal SQLite database. Independent
  replay confirmed the original database hash stayed unchanged. Tests use temporary
  databases. `pip check` reports no broken requirements.

Reproduce the disposable preview with `python scripts/preview_desktop.py`.
Screenshots and timing JSON are under ignored `data/sources/desktop_preview/`.
Timings vary with machine load and are smoke measurements, not benchmarks against
identical historical application source.

## Dependencies and storage

Installed only PySide6-Essentials 6.12.0 and its matching shiboken6 dependency.
Downloaded wheels total 83,419,271 bytes (83.4 MB); wheel plus uncompressed package
payload totals approximately 305.5 MB, within the approved 150 MB download and
500 MB added-storage limits. Existing catalog/vector files were reused.
Wheel hashes are recorded in ignored `data/sources/qt_dependency_report.json`.
Qt package license notices remain bundled with the installation; upstream package:
[PySide6-Essentials](https://pypi.org/project/PySide6-Essentials/6.12.0/).

## Next evaluation

Collect feedback on fresh batches, including taste negatives and familiarity as
separate information. Compare frozen candidate sets using independent judgments
before changing feature weights or enabling a learned model. Numerical audio
similarity still does not establish matching vocals, instrumentation, lyrics,
language or verified genre.
