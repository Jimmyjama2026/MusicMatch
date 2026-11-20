# Dataset source and modification notice

`dataset.csv` is a modified subset of **Spotify Dataset 1921-2020, 600k+ Tracks**, by **Yamac Eren Ay**, Kaggle version 1 (publisher update: March 13, 2022).

Source: https://www.kaggle.com/datasets/yamaerenay/spotify-dataset-19212020-600k-tracks

Publisher metadata: https://www.kaggle.com/api/v1/datasets/view/yamaerenay/spotify-dataset-19212020-600k-tracks

This source data and the modified `dataset.csv` are provided under the unmodified **Community Data License Agreement – Sharing, Version 1.0 (CDLA-Sharing-1.0)**. License text: https://cdla.dev/sharing-1-0/

## Changes made for MusicMatch

The downloaded tracks.csv contains 586,672 rows. We validate identities and the four required audio features, normalize the title/ID column names, convert artist lists to display strings, sort by descending snapshot popularity (track ID breaks ties), remove duplicate track IDs and title/artist recordings, then retain 200,000 songs from 523,913 valid unique songs. A dataset_notice column identifies this modification, attribution, and license. The artist-level CSV is not used in CSV selection; the later artist-genre fallback reads it separately.

The selected popularity values range from 34 to 100; release dates range from 1923 to April 13, 2021. Despite the publisher's title, the file includes early 2021 releases. This is **not a top-200,000-all-time chart or a current catalog**, and the popularity scores are historical snapshots, not live stream counts. Popularity coverage can improve recognizable-song availability but does not establish recommendation quality.

The later [artist genre fallback](ARTIST_GENRE_FALLBACK.md) separately imports genres
from the archive's artist CSV, joined by exact Spotify artist IDs. This does not modify
the song CSV or turn artist genres into verified recording labels. The same source
attribution and CDLA-Sharing-1.0 notice apply to that derived index.

## English-language and US coverage audit

This catalog is international. Its source columns include audio features, artist identities, titles, release dates, and historical popularity, but no track-language, artist-country, or US playback-market field. **An English-language or US filter has not been applied**, and the proportion of English or US songs is unknown. ASCII characters and Latin-script titles are not reliable evidence of sung language or country. We retain the original titles and do not invent these labels.

Primary-source metadata research found three different concepts that must stay distinct:

- Spotify's [Get Track reference](https://developer.spotify.com/documentation/web-api/reference/get-track) describes market availability as countries where a track can be played. US availability does not establish US origin or English lyrics; the documented track object has no sung-language property.
- MusicBrainz's [Artist documentation](https://musicbrainz.org/doc/Artist) defines an artist's area as the place the artist is primarily identified with, often but not always the birth/formation country. That does not establish a recording's language or playback availability.
- MusicBrainz's [Release documentation](https://musicbrainz.org/doc/Release) defines release language as the language of the release and track titles, and release country as where it was issued. Neither is a reliable substitute for sung language.

A future enrichment pass should first define whether “US” means artist origin, US release, or playable in the US; then match stable recording identifiers to an appropriate source. Store each language/country claim with its source, match confidence, and retrieval date, keep unknowns explicit, and validate coverage before offering a filter. Recording/work-level language evidence would be needed for an English-lyrics preference. No enrichment service has been connected or bulk queried in this update.

Rebuild with `scripts/refresh_dataset.py`. The raw source archive is cached under ignored `data/sources/`. The earlier project dataset is preserved locally in ignored `data/dataset.original.csv` and an existing backup is never overwritten. Metadata, source columns, selection rules, and SHA-256 checksums for the source archive and selected CSV are in `dataset_metadata.json`. The script validates the replacement through the recommender before replacing the CSV. User feedback stays in a separate SQLite file and is not opened or modified by the refresh script.

Data is provided as-is under the linked agreement. This data license notice does not license the application's code or the original backup from a different source.
