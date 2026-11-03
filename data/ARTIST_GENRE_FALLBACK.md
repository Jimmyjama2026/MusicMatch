# Artist genres as an offline fallback

The user authorized artist-level coverage as an interim alternative to obtaining a
Last.fm key. Song-level evidence still has priority, and artist genres remain identified
as artist evidence.

## Measured coverage

`scripts/build_artist_genres.py` reads the already downloaded `artists.csv` from
`data/sources/spotify-600k.zip`, retaining only artists credited in the current CSV.
It joins by exact Spotify artist IDs rather than artist names. It made no network
requests and did not change the CSV, recording-genre index or personal feedback.

| Measurement | Count |
|---|---:|
| Catalog songs | 200,000 |
| At least one credited artist has genre labels | 192,166 (96.083%) |
| All credited artists have genre labels | 181,584 |
| No artist genre evidence | 7,834 |
| Artists indexed | 39,583 |
| Artist index size | 3,951,360 bytes |

With song-level priority applied, the active engine uses 21 recording labels and
192,146 artist fallbacks, leaving 7,833 unknown songs. One recording label covers a
song without artist labels, so combined coverage is 192,167 songs (96.0835%). A real
catalog request with country and pop/R&B anchors returned five genre-compatible
results in two separate groups in approximately 0.28 seconds on this machine.

The local index and build report are in ignored `data/sources/artist_genres/`.
Attribution: Yamac Eren Ay, [source dataset](https://www.kaggle.com/datasets/yamaerenay/spotify-dataset-19212020-600k-tracks),
CDLA-Sharing-1.0. These are historical artist genres, not current or independently
verified per-song classifications.

## Matching policy

1. Use a retained recording-level genre label where available.
2. Otherwise use the union of genres for credited artists with exact ID matches.
   Preserve which artist IDs supplied the labels and whether all credits were covered.
3. With neither source, keep genre unknown.

Genre overlap is required before known-genre anchors can share an audio neighborhood.
A candidate must overlap every anchor's genres in its chosen group. Audio scores,
shared-artist bonuses and listening bonuses cannot override genre eligibility.
Exact normalized labels are used: a full genre hierarchy is still future work.
Artist genre lists may describe multiple styles, so this is a coarse compatibility
constraint rather than proof that a particular song has each genre.

Explanations say “Shared genres (artist fallback)” whenever either side relies on
artist evidence, preserving separate candidate and anchor source levels in
`genre_context`. `genre_evidence` remains reserved for song-level labels;
`artist_genre_evidence` stores the fallback. Recording labels never union with a
conflicting artist list. Old feedback snapshots can use current evidence only through
the same song ID and exact title/full-credit identity.

Unknown anchors remain separate when the genre index is active. Unknown tracks can
still appear through the explicitly unverified audio fallback; they cannot match a
known-genre anchor. Synthetic/custom catalogs do not load production artist labels.

## Rebuild and validation

```powershell
.\.venv\Scripts\python.exe scripts/build_artist_genres.py
```

Restart MusicMatch and request new suggestions to load the index. Old saved batches
retain their original results and evidence. All **197 tests passed**, including
recording labels overriding conflicting artist genres, same-name artists separated by
ID, artist-based eligibility, source-labelled explanations and anchor snapshots.
