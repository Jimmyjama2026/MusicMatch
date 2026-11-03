# Rich song vectors and preference neighborhoods

Implemented October 31, 2026. This is the current default recommender when the saved vector index is valid. The original four-feature engine remains unchanged as a comparison baseline and fallback. No neural network is trained in this round.

The subsequent [artist-weight update](ARTIST_WEIGHT_UPDATE.md) adds a strong artist-overlap prior to anchor scoring. Its model version supersedes the initial purely numerical neighborhood ranking described below.

## Saved data and representation

The original `data/dataset.csv` already contains all 13 measurements for 200,000 songs and was not rewritten. The offline builder validates the backend's filtered, deduplicated table so IDs and matrix rows match exactly. Ten continuous measurements are valence, tempo, energy, danceability, acousticness, instrumentalness, speechiness, loudness, liveness and duration. Key expands to sine/cosine coordinates, mode to two categories, and meter to seven categories, giving **21 dimensions**.

Bounded continuous features retain their natural ranges and are median-centered. Tempo and duration use log2, then fitted median/IQR scaling; loudness uses median/IQR scaling. Unbounded transformed values are clipped to limit outliers. Initial squared-distance weights are 1 for valence/tempo/energy/danceability/acousticness/instrumentalness, .7 speechiness, .4 loudness, .35 liveness and .3 duration. Circular key uses .08 per coordinate; categorical mode and meter use .02 per encoded coordinate. These are fixed starting choices, not learned or validated taste weights. A zero-IQR unbounded feature contributes zero until a rebuild.

Explicit validity masks keep unknown values separate from music features. All ten continuous features, key and mode were valid in this catalog; two invalid time signatures were masked. Pairwise comparisons require at least seven shared continuous measurements and 70% of the 13 raw measurements. Expanded categorical coordinates do not inflate evidence coverage. No genre or language labels are inferred.

The saved index includes stable track IDs, all transformation settings, feature version, source fingerprint over IDs/raw measurements and an array checksum. Loading verifies compatibility, integrity and row alignment. Atomic generation publication preserves the prior index on interruption. Old generations remain available for concurrent readers rather than being deleted automatically.

Current matrix: **200,000 × 21 float32**, 16,800,000 bytes in memory, plus a 2,600,000-byte raw validity mask. Current compressed generation is approximately **11.15 MB**; three retained development generations and reports total **33,639,245 bytes**. This round downloaded **zero bytes**. The prior source/index/catalog data plus this vector directory total approximately 340.5 MB including the existing CSV/source artifacts, excluding runtime dependencies and unrelated files.

Rebuild deliberately outside the desktop:

```powershell
.\.venv\Scripts\python.exe scripts/build_song_vectors.py
```

The desktop loads `data/vectors/manifest.json` on its existing background worker; it never starts a vector build. Missing, stale or corrupt indexes fall back to the original engine and display a fallback status. Restart after rebuilding to load the new generation.

## Preference neighborhoods and scoring

Each eligible current favorite is an anchor. Up to 32 recent distinct Yes-rated songs may add anchors, with a .08 score penalty relative to explicit favorites. If more than 96 total eligible anchors exist, deterministic farthest-first representative selection preserves separated preferences while bounding work; counts of available/used anchors are saved.

Complete-link grouping requires every pair in a group to be within a .10 distance. It cannot merge distant preferences merely because intermediate likes connect them. Candidate distance is measured to the closest actual anchor, not the center of all favorites. Group spread is retained for explanation, rather than dividing distances by a broad group's spread and rewarding vague matches. Distance uses weighted shared-coordinate RMS, with a small missing-coverage penalty. Cosine similarity and standalone vector magnitude are not separate ranking signals in this version.

Latest No ratings exclude their songs. Up to 32 recent valid disliked anchors add a local penalty of at most .04, decaying with distance. “Already know it” excludes a song without supplying this dislike penalty or an artist dislike. Up to 500 newest distinct ratings are inspected. Yes/No information is profile-scoped; nothing is automatically learned from unrated tracks. Original legacy fallback retains its historical four-feature scoring policy.

Selection adds a .06 penalty for each already selected result from a group and uses a soft two-per-credited-artist cap, including collaborators. Backfill relaxes the cap when alternatives run out. Favorites, Yes anchors, latest No songs, duplicates and requested Fresh exclusions remain excluded. Catalog comparisons stream in chunks; no catalog-wide all-pairs table is created. There is no hard similarity-quality cutoff: the nearest available eligible results can still be poor matches.

For rich results, cached ListenBrainz evidence can adjust confidently joined candidates by at most .02 listening support plus .005 artist preference. These smaller limits fit the new distance scale. Unknown-audio provider discoveries no longer replace a rich result automatically. Metadata-only favorite lists can still use the separately labelled provider route. Unknown audio features are never estimated. Known recording mappings may supply an existing audio record as model input while retaining the originally selected favorite ID in saved resolution context.

## Persistence and future neural training

Each rich recommendation carries its raw measurements, model/feature versions, source fingerprint, anchor/group IDs, spread, representative counts and score components. The existing SQLite song/context snapshots preserve these fields alongside ratings without a schema migration. Older batches remain historical snapshots; generating new suggestions does not rewrite them.

`data/learning_records.py` reads latest ratings and original contexts using an explicitly closed read-only database connection. `partition_examples` assigns title/full-credit aliases to one deterministic training/evaluation partition; familiarity-only responses are separate. The returned records are audit provenance, not direct training inputs. `prepare_model_inputs` strips historical ranking/neighborhood outputs, removes all held-out identities and the candidate itself from favorite contexts, and emits raw feature inputs. A future evaluator must rebuild a fresh model/neighborhood state using training likes only. Do not train on raw audit contexts or claim past live batches were held out. Old records with missing feature versions need explicit resolution before neural training.

## Verification and limits

All **80 tests passed in 11.97 seconds**. Coverage includes vector persistence/checksums/source drift, invalid measurements, circular keys, skewed instrumentalness, distinct slow/speech-heavy and fast/acoustic preferences, complete-link chaining, partial-feature overlap, representative caps, collaborator diversity, aliases/exhaustion, saved metadata favorites, provider provenance, profile isolation, clean evaluation inputs and a real Tk workflow saving rich recommendation feedback.

The independent reviewer challenged every new component and integration, then accepted the corrected changes without remaining blockers. Production layout and scrolling were unchanged. Tests use temporary databases; the actual profile database was read only for smoke measurements.

Against the six current saved favorites, the real catalog loaded all 200,000 vectors without warnings, formed five groups, and returned five neighborhood-supported suggestions. Four paired warm requests averaged **142.1 ms original / 124.3 ms new hybrid**, maxima **160.0 / 141.7 ms**; startup took **3.80 seconds**. This single-machine smoke measurement used no rating feedback or Fresh exclusions and is not a latency guarantee. See [raw measurements](neighborhood_run_report.json).

These measurements establish the path works, not that suggestions fit the user's taste. The source remains an international historical catalog with no verified language/genre fields. Richer numerical matches can still differ in vocals, production, genre or language. Text analysis and richer sound embeddings remain separate/deferred. User judgments and a fresh held-out comparison are required before claiming better recommendation quality or tuning the fixed weights.
