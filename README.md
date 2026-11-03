# MusicMatch

A local desktop music recommender with explanations and human feedback.

The default desktop now uses a charcoal and royal-blue Qt interface. See the
[delivery notes](data/MODERN_DESKTOP_DELIVERY.md) for this round's changes and checks.
The [neighborhood map and discovery update](data/NEIGHBORHOOD_VISUALS.md) adds saved
visual explanations and two unfamiliar-artist slots to normal five-song requests.
The [title screening, steering and A/B update](data/STEERING_LANGUAGE_COMPARISONS.md)
adds local title-language estimates, request-only controls under More like this,
and optional comparisons that influence future recommendations without dislikes.
The [feedback and coverage fix](data/FEEDBACK_AND_COVERAGE_FIX.md) preserves scroll
position when voting, balances liked-artist anchors and applies Too slow/Too fast
feedback directionally within the relevant neighborhood.
The [local neural learning setup](data/NEURAL_LEARNING_SETUP.md) adds durable
judgment history and bounded background shadow training, screens suggestions for
English titles only, and reduces song duration's matching weight by 90%.
The [genre training inputs](data/NEURAL_GENRE_INPUTS.md) add saved candidate/anchor
genres, overlap and evidence-source indicators to that shadow learner.
Adding a song to [Liked songs also counts as a training Yes](data/FAVORITES_AS_TRAINING_YES.md),
with duplicates merged and search-added likes supported without a recommendation anchor.

## Preference neighborhoods

The [artist genre fallback](data/ARTIST_GENRE_FALLBACK.md) supplies genre evidence for
192,166 of 200,000 songs (96.1%) from the cached source's artist IDs. Available song-level
labels take priority; artist-based matches are identified in explanations. Genre overlap
is required for known-genre neighbourhoods and suggestions. Combining both sources
covers 192,167 songs; the remaining 7,833 have an explicitly unverified audio fallback.

The current default uses saved 21-dimensional vectors from the CSV's 13 song
measurements, matches individual liked-song neighborhoods, and selects varied
results across those groups. See [implementation and measurements](data/NEIGHBORHOOD_IMPLEMENTATION.md).
The vector index is built offline with `scripts/build_song_vectors.py`; the desktop
loads it in the background. Missing or stale vectors use the original model with
a fallback status. Restart the app after an index build and request new suggestions;
saved older batches keep their original results.

## Offline enrichment pilot

The approved enrichment implementation and its ranking policy are documented in
`data/ENRICHMENT_IMPLEMENTATION.md`. Optional MusicBrainz/ListenBrainz data is
collected by `scripts/acquire_catalog.py` outside the desktop app; no search or
recommendation performs network requests. Missing enrichment preserves the original
audio recommender. New catalog-only tracks never receive invented audio features.
The licensed MulJam text experiment (`scripts/build_text_index.py`) persists sparse
song vectors and compares them on demand, separately from personal recommendations.
See `data/TEXT_SIMILARITY_EXPERIMENT.md` for its measured coverage and limitations.
See [the pilot run report](data/ENRICHMENT_RUN_REPORT.md) for measured storage,
validation, performance and remaining coverage limitations.
The [second review](data/SECOND_REVIEW_AND_NEXT_ROUND.md) records additional fixes,
the latest validation and proposed next-round work.

## Run in VS Code

Open the MusicMatch folder in VS Code. Select `.venv\Scripts\python.exe` using **Python: Select Interpreter** (Microsoft Python extension).

In the integrated PowerShell terminal:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

Or use Run and Debug > **MusicMatch desktop** with the Python Debugger extension.
Use `python main.py --legacy` (with the same interpreter) for the earlier Tk window.
Running `data/main.py` directly also opens that earlier window. No browser or API account is needed.

If you need a fresh environment, run `py -m venv .venv` first. Python 3.12 or later is the supported project baseline.

## Use the window

The new desktop has **Discover**, **Liked songs**, and **History** navigation.
Search by title and optional artist, add favorites, then select **Suggest songs**.
Use **Why this match?** for feature comparisons and **More like this** to focus on
one favorite while preserving your full liked list. **Fresh only** skips prior
suggestions. Yes/No feedback, optional No reasons, profiles and saved history remain
local. Reset Test requires confirmation. Search and ranking run on a serialized
worker; changing profiles clears the previous profile's visible results.

The following describes the retained classic interface:

1. Enter a song title and optionally an artist to narrow the results. Leave the title blank to search by artist alone. Click **Add** beside a result; it changes to **Added** after saving.
2. Keep searching and adding favorites. **Add more songs** clears and focuses the search. Filter favorites by title or artist, select one, and click **Remove selected**. **Hide favorites** collapses the list without deleting saved songs.
3. Click **Suggest songs** for up to five matches and explanations comparing song features with your favorites.
4. Click **Yes** or **No** beside each suggestion. The saved indicator appears only after the write succeeds. You can change your answer.

Search and recommendation work runs in a background worker so the window stays responsive. Changing your favorites clears outdated suggestions; click Suggest songs to generate a fresh batch.

The Round 1 interface uses BYU navy, royal blue and white, with one scrolling page. Recommendation cards reflow as the window changes size. Open a card's explanation for detailed feature comparisons; your saved Yes/No choice stays visibly selected, including after reopening the app.

Round 2 adds separate title/artist search, per-result saved Add/Added buttons, and filterable, collapsible favorites. Added indicators follow the current profile's saved favorites after new searches and restarts.

Round 3 adds saved recommendation history with All/Yes/No/Unrated filters. Opening an older batch shows its original favorite context without replacing your active favorites. A No rating can include an optional preset reason; changing it to Yes clears that reason. Future suggestions exclude tracks whose latest rating is No. Fresh suggestions also skip every song previously suggested in the active profile. If that exhausts the available catalog, no older batch is restored as the current result; history remains available.

## Local context storage

`data/feedback.sqlite3` is created automatically. It contains:

- Recommendation batches: timestamp, algorithm version, and complete favorite-song snapshots.
- Suggested songs: track IDs, metadata, audio features, explanations, and distance scores linked to the original batch.
- Feedback: Yes/No, an optional No reason and the latest response timestamp linked to a specific batch and song.

Changing a vote updates that batch/song rating rather than creating a duplicate. A new recommendation request creates a separate batch. Favorites, the latest recommendations, ratings and the active profile survive app restarts. Personal and Test profiles have isolated context. Only Test can be reset; Personal data is protected from that button. Existing databases migrate automatically into Personal. SQLite files are ignored by Git. This is a local prototype; there are no accounts or cloud uploads.

The default model matches rich vectors to individual favorite/Yes anchors, gives a strong boost to shared artists (including collaborators), groups close anchors without averaging all tastes together, and uses bounded local dislike penalties plus artist/group diversity. Artist IDs take precedence where available; exact normalized names are a fallback when IDs are missing. Ratings take effect on the next request. “Already know it” suppresses repeats without training a dislike on this rich path. The four-feature average-distance engine remains available in code as the historical baseline/fallback. Explanations describe numerical feature neighborhoods and artist evidence; they do not establish lyrical, genre, language or perceived-sound similarity. Weights remain initial heuristics; no neural network is trained yet.

## Verify

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Tests use temporary synthetic datasets and databases, including migration, profile isolation, saved-context restoration, preference adjustment, and Tk workflow/geometry checks. The geometry check briefly maps a test window at narrow and wide sizes. No audio playback or live music-service connection runs in the desktop; optional service data is acquired separately by the offline collector.

## Dataset

The catalog contains 200,000 valid unique recordings selected by highest popularity from Yamac Eren Ay's historical Spotify dataset (version 1, March 13, 2022). Its 586,672 source rows yield 523,913 valid unique recordings before selection; selected popularity values range from 34 to 100 and release dates span 1923 through April 13, 2021. This is an international historical snapshot, not a current chart or the top 200,000 songs of all time. The source lacks verified language and US-market fields, so the catalog is not filtered to verified English or US tracks. See `data/DATASET_SOURCE.md` for attribution, source audit, CDLA-Sharing-1.0 license and modifications, and `scripts/refresh_dataset.py` for reproduction.
