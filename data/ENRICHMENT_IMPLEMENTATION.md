# Offline enrichment implementation

The rich-vector model now supersedes the four-feature ranking policy below when its index is available. See [NEIGHBORHOOD_IMPLEMENTATION.md](NEIGHBORHOOD_IMPLEMENTATION.md) for the current default, smaller listening adjustments and removal of the mandatory discovery slot on rich results. The earlier policy remains relevant to the legacy fallback.

## What changes the personal recommender

The desktop imports `data.hybrid.MusicRecommender`, a network-free facade around the original audio engine. The original feedback database and schema are unchanged. Initialization/search/recommendation remain on the existing single background worker; the layout, widget set and scrolling implementation are unchanged. The optional local sidecar is `data/enrichment/catalog.json`. It is loaded once at startup; refresh acquisition outside the app and restart the app to pick up changes. Missing, empty or invalid optional data leaves the original audio results available. An invalid sidecar records `enrichment_warning` on the engine; inspect the collector report for acquisition errors rather than interpreting failures as absent songs.

MusicBrainz tracks without audio can appear in title/artist search and be saved as favorites. Their missing measurements remain missing. Cached ListenBrainz artist-based recommendation edges are the only new live ranking signal in this phase. A title/full artist-credit match and duration agreement within two seconds, with only one candidate in either direction, are required before mapping an existing audio recording automatically to a MusicBrainz recording. This is conservative matching, not a guarantee of identical recordings. Artist resolution is marked provisional unless an ID override was manually verified. Minimal browse responses provide a queried-artist association rather than a full credited lineup; these are explicitly marked credit-incomplete and cannot map automatically to existing audio recordings. Version disambiguation is retained in the displayed title where provided. Names, original provider IDs, licenses and timestamps remain available in the sidecar.

### Explicit ranking policy (experimental, not optimized weights)

1. Compute the original scaled four-feature audio distance and bounded recent-feedback adjustment using only favorites with valid audio. The existing engine supplies up to 50 candidates for normal five-result requests. Unsupported metadata favorites do not get invented features.
2. Seed provider relationships using a mapped favorite's artist IDs, or an exact credited artist name matched to a manually reviewed artist ID with no conflicting identity known in the sidecar. Name-only associations remain approximate when the favorite recording is unmapped; unseen namesakes cannot be ruled out. For each candidate with a confident MusicBrainz recording mapping, count which favorite artist IDs have an actual cached ListenBrainz recommendation edge to it. Support is that count divided by the number of matched favorite artist IDs. Missing evidence is neutral. Subtract at most 0.12 times this support from the original audio ranking score.
3. On these supported candidates only, apply a bounded artist preference adjustment: `0.04 * sum(Yes=1, No=-1) / (vote_count+4)` using up to 500 newest distinct-song profile ratings and credited artist names. This is a small shrinkage heuristic; it is not a trained neural model. The original audio adjustment still applies separately. Store the audio score/model version, listening support, listening adjustment and final model version with the recommendation.
4. A mixed recommendation batch can reserve at most one slot for a provider-associated recording outside the audio shortlist. It is explicitly labelled as a ListenBrainz discovery, with audio and lyric similarity unknown; unrelated score scales are never sorted together. With metadata-only favorites, eligible results use provider relationships only. A single-result request keeps the audio result where available. Favorite aliases, latest No votes and fresh-history exclusions remain excluded.

The 0.12 and 0.04 constants are conservative initial choices, not measured optimums. The audio shortlist bounds work but means some existing audio recordings can enter only through the provider-discovery slot. Shared artists and associations are not evidence of similar sound or lyrical themes.

Exclusions use the same normalized title/full-artist-string policy as recommendation deduplication across catalog IDs, even where recording mapping is unavailable. This only suppresses repeated displayed songs; it does not transfer audio features or establish a verified recording identity. Candidate channels are deduplicated before selecting their result slots. An exhausted provider candidate set returns no suggestions normally, while a metadata-only favorite with no cached provider support receives a missing-data message.

## Persisted lyrical representations

The MulJam experiment is separate: no GUI import, no changes to personal ranking, no assumed overlap with the 27 artists. It uses licensed text retained in the ignored research source directory. Word and two-word TF-IDF features are fitted separately for each supplied language, capped at 20,000 features, normalized and persisted as sparse float32 arrays with JSON vocabulary/IDF, model version and corpus hash. The first fit analyzes each song once. Later queries compare one saved row to its language's matrix and rank positive cosine scores; there is no N-by-N stored similarity table and no per-query API call. Changing the corpus changes IDF, so it requires a versioned rebuild. This is lexical similarity, not validated understanding of heartbreak, negation, metaphor or multilingual equivalence.

Run `python scripts/build_text_index.py` to reuse downloaded source and saved index, or add `--download` for the first bounded acquisition. See TEXT_SIMILARITY_EXPERIMENT.md for provenance and exact measured corpus/storage/query results. No paid model, extra dependency, audio or LRCLIB download is involved.

## Acquisition and validation

Run `python scripts/acquire_catalog.py --transport curl --artist-ids data/verified_artist_ids.json` separately from the desktop. The CLI is resumable; starts from the 27 artists in coverage_audit.json; honors provider request pacing and Retry-After; never weakens TLS verification; caps per-response and cumulative transfer/storage; keeps a conservative transfer reservation across failures; and preserves prior catalog data on partial/failed refresh. Credentials are not required for the public endpoints used here. No personal account is connected or personal listening history uploaded. A stale acquisition lock requires confirming the recorded process is no longer active before removing it.

Acquisition currently browses all credited recording versions. It explicitly does not claim a verified studio-only discography; live/remix/unofficial filtering remains a follow-up after usable catalog retrieval. Completion flags distinguish metadata and listening sources. File/report errors are part of the coverage report, not interpreted as zero provider coverage.

The current cache is a resumable frozen snapshot, with no automatic expiry or explicit refresh switch. Rerunning the CLI reuses successful cached responses; it does not guarantee new provider releases or relationships appear. Controlled revalidation is a next-round proposal. A future text-model version change also requires a new index location or explicit rebuild; the current directory name only includes the corpus hash. See [second review and proposals](SECOND_REVIEW_AND_NEXT_ROUND.md).

## Quality evaluation before changing weights further

- Preserve the original model and per-channel scores as the comparison baseline.
- Collect Yes/No labels in MusicMatch; do not treat missing votes or unplayed songs as dislikes.
- Compare baseline and enriched candidates prospectively using the same favorite context, exclusions and fixed source snapshot. Judge candidate sets with source labels hidden during evaluation to reduce expectation bias.
- Keep evaluation labels separate from the votes supplied to the ranker. Report rated count, coverage, approval rate and uncertainty; sparse biased feedback is insufficient for a claim of improved recommendations.
- Evaluate the licensed text corpus separately, with judged same-language pairs. Technical round-trip/query tests establish implementation behavior, not recommendation quality.
- Do not introduce automatic learned cross-channel weights until enough held-out data exists. Text can join the live ranker only when permitted text and verified song identity overlap are established.

## Deferred priority

Richer sound understanding/audio embeddings remain a future priority. This phase does not acquire audio or add new acoustic analysis. Existing four-feature audio ranking remains available.
