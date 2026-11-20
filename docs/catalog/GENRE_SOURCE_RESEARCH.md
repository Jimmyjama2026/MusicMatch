# Song-level genre coverage research

Researched November 2, 2026. The objective is song-level evidence for the existing 200,000-song CSV, without inheriting artist or album genres.

## Findings measured against this project

### Wikidata: 2,300 exact Spotify-ID candidates

Queried the public table of song entities with both [Spotify track IDs (P2207)](https://www.wikidata.org/wiki/Property:P2207) and [genres (P136)](https://www.wikidata.org/wiki/Property:P136), then joined it to our CSV locally. The query sent no catalog songs or saved preferences.

- Retrieved 10,654 genre associations across 8,160 distinct Spotify track IDs. The 50,000-row safety limit was not reached.
- **2,300 catalog tracks matched exact Spotify IDs: 1.15% of the catalog.**
- Examples include “drivers license” (pop variants), “Astronaut In The Ocean” (hip-hop), and “Blinding Lights” (electropop/synthwave).
- These are candidate song-level annotations, not 2,300 newly verified recording labels. Song entities can combine multiple recording versions; statement references, version identity and genre normalization require review before the hard recommendation gate uses them.
- Wikidata structured data is [CC0](https://www.wikidata.org/wiki/Wikidata:Licensing). No API key is required for the [query service](https://www.wikidata.org/wiki/Wikidata:SPARQL_query_service).

Reproduce with `scripts/audit_wikidata_genres.py`. Query, raw response and matched IDs are saved under ignored `data/sources/genre_research/wikidata_audit.json` and `wikidata_song_genres.json`. This audit does not modify recommendations.

### AcousticBrainz / Last.fm: substantial bulk data, mapping bottleneck

Downloaded the **Last.fm-derived annotation tables only**, from the authors' [Zenodo release](https://zenodo.org/records/2553414). Both published MD5 checksums matched. Train plus validation download totalled **27,806,778 bytes**, with **686,978 unique recording IDs**. Audio and the multi-gigabyte feature archives were not downloaded.

The [authors distinguish](https://github.com/MTG/acousticbrainz-genre-dataset) Last.fm/Tagtraum recording-tag-derived labels from AllMusic/Discogs album annotations propagated onto tracks. The Last.fm tables are therefore relevant to our requirement, although their genres and hierarchy are inferred from community tags. License: CC BY-NC-SA 4.0, with attribution to the dataset authors and source.

Our previous pilot provides only **44 conservative catalog-to-recording-ID joins**. Of those, **6** occur in these Last.fm tables; all six already have usable MusicBrainz labels. The audit therefore found **zero additional labelled songs within those 44 joins**. This is not an estimate of overlap across all 200,000 songs: the remaining catalog lacks the necessary crosswalk. Resolving recording IDs is a prerequisite to exploiting this bulk source.

Reproduce with `scripts/audit_genre_sources.py`. The compressed annotations and `lastfm_bulk_audit.json` are saved under ignored `data/sources/genre_research/`. No bulk labels were imported into the recommender.

## Other sources evaluated

| Source | Fit for song-level genres | Practical limitation |
|---|---|---|
| [Live Last.fm track API](https://www.last.fm/api/show/track.getTopTags) | Best next source to test: track tags can be requested using artist/title or recording MBID; counts support filtering. | Requires a user-issued API key. Actual catalog coverage has not been measured. Tags include non-genres. |
| [Original MSD / Last.fm dataset](https://www.auditory.org/mhonarc/2011/msg00791.html) | Authors announced 505,216 tracks with tags, not necessarily genre tags. | Historical 2011 collection; title/artist or MSD-ID crosswalk needed. The original distribution pages timed out during this research. |
| [Tagtraum MSD annotations](https://www.tagtraum.com/msd_genre_datasets.html) | Published CD2C has 191,401 unambiguous annotations; CD2 has 280,831 including ambiguous annotations. | MSD identifiers rather than our Spotify IDs; historical coverage and research-only noncommercial terms. |
| [Discogs release metadata](https://support.discogs.com/hc/en-us/articles/360005006334-Database-Guidelines-1-General-Rules) | Useful contextual evidence. | Genre is a release field; copying it onto every song would fail the requirement. The AcousticBrainz AllMusic/Discogs subsets explicitly do this. |
| [AcousticBrainz predictions](https://acousticbrainz.org/data) / [Essentia classifiers](https://essentia.upf.edu/models.html) | Potential recording-level predicted evidence. | Distinguish predictions from curated tags. AcousticBrainz needs matched recording IDs; new classifier runs require audio/embeddings, not our CSV measurements alone. |

## Why live Last.fm is the next recommendation

The CSV has **69,041 rows dated 2012 or later (34.52%)**, including **21,943 dated 2019 or later**. These are dataset release dates, not verified original recording dates: reissues can contain older recordings. They nevertheless show why historical bulk datasets alone are unlikely to cover the full catalog. The era counts are saved in `catalog_eras.json`.

The live [track.getInfo endpoint](https://www.last.fm/api/show/track.getInfo) supplies title, artist, optional MBID and duration for identity checks; [track.getTopTags](https://www.last.fm/api/show/track.getTopTags) supplies ranked tag evidence. A key is required even though these reads do not require a signed-in user's session. The [key registration page](https://www.last.fm/api/account/create) currently redirects to login.

The [API terms](https://www.last.fm/api/tos) require attribution and links, documented API access, rate-limit compliance and specify a 100 MB reasonable usage cap. Last.fm requests prior contact for commercial or research/academic use. The API provides conditional access rather than an unrestricted bulk-data license; check applicability before scaling a pilot or distributing collected labels. API tag counts must not be treated as MusicBrainz vote counts.

Recommended next work:

1. Review Wikidata version identity and genre references for the 2,300 exact-ID candidates, preserving provenance and uncertainty.
2. Once a Last.fm key is configured locally as `LASTFM_API_KEY`, measure a bounded 500-song sample across popularity ranges, eras and known/missing genres. Report identity matches, genre-bearing matches, acceptable label strength, ambiguous versions, and newly covered songs separately.
3. Map spelling aliases into one genre vocabulary and distinguish parent genres from subgenres. Exclude moods, decades, languages, personal tags and artist names. Do not let a generic shared tag erase a strong incompatible genre signal.
4. Expand only after measured yield and identity quality justify it, within the provider's rate and storage limits. Use the downloaded historical tables where verified recording mappings exist.

No honest full-catalog Last.fm coverage percentage is available yet. Dataset size, exact-ID candidates, verified recording joins and accepted recommendation labels are different measurements.
