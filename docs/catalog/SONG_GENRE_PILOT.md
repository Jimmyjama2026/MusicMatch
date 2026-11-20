# Recording-level genre pilot

The later [artist fallback update](ARTIST_GENRE_FALLBACK.md), explicitly requested by
the user, adds broad artist-based coverage while preserving recording-label priority.
The no-artist-inheritance policy below describes the original song-only pilot.

Implemented November 2, 2026. Artist and album genres are not inherited as song labels.

## Acquisition and measured coverage

`scripts/acquire_song_genres.py` retrieves MusicBrainz recording genres offline, outside the desktop. It starts with conservative existing recording mappings, then searches catalog songs by title and artist. The optional `--include-saved-favorites` flag prioritizes saved favorites and sends their song identities to MusicBrainz; the user explicitly authorized this pilot. Favorites are read through a closed read-only SQLite connection.

Every detail response is checked against the catalog's exact normalized title, full artist-credit set, and duration within two seconds. Ambiguous search results, truncated searches and disambiguated versions are left unresolved. This is conservative metadata matching, not fingerprint verification.

The completed targeted pilot inspected **69 of 200,000 songs**:

| Result | Songs |
|---|---:|
| Usable recording genres | 21 |
| Recording genres present but votes too weak | 11 |
| Matched recording without genre labels | 12 |
| Recording identity unresolved | 25 |

These songs were selected using existing joins, approved favorites and popularity, not random sampling. The 21 labels cover **0.0105% of the full catalog**; this pilot does not establish broad coverage or a representative success rate. Transfer accounting is approximately 2.51 MB, including conservative reservations. The final run completed without errors. Earlier response-size and transient Windows file-lock failures were resumable and were not recorded as missing genre evidence.

Retained files are `data/sources/song_genres/index.json`, `report.json`, and cached responses. That directory is ignored by Git. Each labelled record retains source URL, recording ID, retrieval time, attribution, license, identity basis, original positive genre vote counts and the label-selection policy.

MusicBrainz genre associations are supplementary data under **CC BY-NC-SA 3.0**, credited to MusicBrainz contributors; they are not CC0 core metadata. See [MusicBrainz database licensing](https://musicbrainz.org/doc/MusicBrainz_Database) and [recording genre API](https://musicbrainz.org/doc/MusicBrainz_API).

## Stronger label selection

Community tags can conflict. A label is used only when its net vote count is at least two and at least 75% of the strongest genre's vote count on that recording. Weak alternatives remain in `genre_votes` for review. This is an initial conservative heuristic, not a calibrated confidence probability or proof that the label is correct. For example, the pilot retains country for “Take Your Time” and indie folk for “invisible string,” excluding weaker conflicting tags.

## Recommendation behavior

When usable recording labels exist, favorite/Yes anchors can share a neighborhood only if every pair shares a retained recording genre **and** passes the existing audio-distance radius. Unknown anchors remain separate. A candidate must share a retained genre with every anchor in its selected group; artist bonuses, listening support, steering and feedback cannot override this eligibility gate. Exact shared labels are required in this first version: there is no automatic genre hierarchy or inference that country and bro-country are equivalent.

A known-genre anchor does not accept an unknown-genre candidate. Unknown anchors may still retrieve unknown tracks through an explicitly labelled, unverified audio fallback. This fallback does not establish genre similarity. If no usable index is available, the original audio path remains available; broad genre-aware behavior cannot be claimed before coverage improves. Sparse labels can return fewer than five suggestions; mismatched songs do not fill the gaps for known-genre anchors.

Results retain `genre_evidence`, `genre_context`, and recording-label evidence on anchor snapshots. Explanations identify shared song genres or unknown-genre fallback. The map still projects audio coordinates: genre constraints affect group colors, not dot coordinates. Saved old batches remain historical snapshots. Restart the desktop and request fresh suggestions to load new evidence.

## Run and resume

```powershell
.\.venv\Scripts\python.exe scripts/acquire_song_genres.py --limit 50 --transport urllib
# With explicit authorization to query the saved favorites:
.\.venv\Scripts\python.exe scripts/acquire_song_genres.py --limit 50 --transport urllib --include-saved-favorites
```

Successful inspections are skipped on resume. `--artist` limits the catalog by artist text; `--refresh` reprocesses existing entries while reusing cached responses. API failures stop the bounded run and remain retryable. The shared client caches, throttles and caps transfers and retained data at 90 MB each. There is no unattended full-catalog job, new API credential, audio download or model training.

## Validation and remaining work

All **195 tests passed**. Tests cover identical audio/same-artist genre conflicts, candidate exclusion, unknown anchors, weak-vote filtering, recording-version ambiguity, and no artist-tag inheritance. Earlier full-suite validation hit one transient Windows replacement error in an existing acquisition test; that test and the subsequent full suite passed.

Broad song-level coverage remains unfinished. MusicBrainz alone has substantial missing labels and recording ambiguity in this pilot. A next source, such as Last.fm track tags, needs separate coverage measurement and filtering; artist-tag coverage is not a substitute for this requirement.
