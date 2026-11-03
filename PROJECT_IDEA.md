# MusicMatch

A music discovery app that recommends songs from your favorites and explains each match.

## Purpose
CS111 project requiring at least 10 hours of actual research, coding, debugging, and testing. Build programming skills and a portfolio project relevant to machine learning and software engineering. AI assistance is allowed. Keep an honest time log of your own work.

## Status — October 29, 2026
The original command-line prototype has been extended into a local Tkinter desktop application. Run `main.py` from the root or `data/main.py` directly; VS Code launch instructions are in README.md. The user confirmed the existing Python environment works.

## Implemented
- Load and validate the local dataset; deduplicate recordings and track IDs.
- Search titles and artists, including partial and approximate title matches.
- Add multiple favorites, remove selections, and explicitly request suggestions.
- Rank up to five songs using scaled valence, tempo, energy, and danceability with average Euclidean distance.
- Explain recommendations using actual feature comparisons with favorites.
- Rate each suggestion Yes or No and change the answer when needed.
- Store local SQLite context: original favorite snapshots, suggested-song metadata/features, reasons, distance scores, algorithm version, batch timestamps, and ratings.
- Keep storage separate from the interface and run costly operations in a background worker.
- Provide requirements, VS Code launch configuration, and meaningful backend tests.
- Round 1 interface: BYU colors, whole-page scrolling, responsive recommendation cards, expandable explanations and visible saved Yes/No selections.
- Round 2 interface: combined title/artist filters, per-result Add/Added controls and filterable, collapsible saved favorites.
- Round 3: profile-scoped recommendation history and rating filters, optional No reasons, latest-No exclusions and fresh suggestions that skip previously shown tracks.

## Current boundaries
Personal and Test profiles persist favorites, latest recommendations and votes separately. Up to 500 recent distinct-song ratings in the active profile make a small bounded adjustment to audio-feature ranking; this is an initial transparent preference heuristic, not a guarantee of taste. Only Test can be reset. The app is a local prototype with no playback or live music-service account connection. Optional provider data is collected offline. Reasons distinguish audio-feature similarity from provider listening associations; lyrics remain a separate experiment and neither signal guarantees taste compatibility.

## Verification and review
The team performed critique/revision passes across the interface, backend, and launcher. The catalog now contains 200,000 valid unique recordings selected by historical popularity from a documented international Spotify dataset; source, licensing and modifications are recorded in data/DATASET_SOURCE.md. The source has no verified language or US-market fields, so no verified English/US filter is claimed. Automated tests cover search, ranking exclusions, invalid data, context persistence, changed votes, profile isolation, migration and preference adjustments. See the test suite and README for repeatable verification.

## Next priorities
1. Have the project manager try the desktop workflow and collect real Yes/No ratings.
2. Inspect the collected context and evaluate the initial preference adjustment against unadjusted rankings.
3. Compare recommendations against a baseline such as same-genre suggestions and report actual results.
4. Document lessons learned and actual time spent; maintain dataset provenance and licensing notices.

## Possible later extensions
Artist diversity, a discovery slider, saved favorite lists, feedback history/export, and music-service integration. Keep the initial focus on the five requested desktop and feedback criteria.

## Approved enrichment pilot

Implemented offline catalog/listening acquisition, a bounded optional listening-association ranker, and an isolated licensed MulJam lexical-similarity experiment. See data/ENRICHMENT_IMPLEMENTATION.md for the algorithm, storage and evaluation boundaries. Actual provider-acquisition coverage is reported separately; available code does not imply downloaded coverage or measured recommendation improvement. Richer sound analysis/audio embeddings remain a deferred user priority; do not forget this direction when revisiting newer-song coverage.
