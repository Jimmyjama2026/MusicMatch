# Enrichment pilot results

Implementation and review completed October 30–31, 2026. The bounded acquisition pass finished with partial coverage; no collector remains running.

This records the first implementation run. See the [second review](SECOND_REVIEW_AND_NEXT_ROUND.md) for subsequent fixes, the latest 52-test validation and next-round proposals.

## Measured acquisition

The retained sidecar contains **4,115 recording entries**: 3,439 from MusicBrainz browsing and 676 neighbor records resolved through ListenBrainz's MusicBrainz metadata service. All 27 artist IDs were reviewed; 22 artists have MusicBrainz recording rows. There are **885 cached artist-based recommendation edges** across ten seed artists and **2,054 aggregate popularity records**. The runtime loads **725 distinct seed-to-recording relationships** with usable metadata; 160 edges lacking recording metadata are skipped. Popularity is retained for inspection but is not a new ranking weight. These are recording versions, not 4,115 unique songs.

Additional retained source/cache/index/catalog files total **27,779,345 bytes (27.78 MB)**. Including the existing 279,052,278 bytes of CSV/source artifacts gives **306,831,623 bytes (0.307 GB)**. The catalog collector ledger records a **76,090,652-byte transfer upper bound**, plus the separately measured 12,880,118 bytes of text responses. This combined conservative bound is approximately **88.97 MB**, not an exact count of successful network downloads. All are well below the agreed data limits. Runtime dependencies and unrelated project files are excluded from these data-artifact totals.

The final snapshot reports six errors: a transient local atomic-file replacement denial for Plain White T’s (its 100 rows were nevertheless retained), MusicBrainz HTTP 503 for Coldplay, TLS EOF failures for Jack Johnson/Benson Boone/Jordan Davis, and a circuit-breaker skip for Post Malone. The remaining artists were deliberately paginated only partially, and listening collection was skipped on the final breadth-first subset. Completion flags remain false. Resuming is supported, but this report does not claim full coverage.

See [machine-readable measured counts](enrichment_run_stats.json) for every artist, source totals, errors and byte accounting. The raw sidecar's `requested_artists` field describes the last subset request, while its retained `artists` list contains all 27 resolved IDs. Artist counts in the report are derived from retained recording rows rather than the last pagination pass's counters.

## What is implemented

- Offline MusicBrainz catalog and ListenBrainz aggregate/recommendation collector, with verified artist IDs, request pacing, bounded retries, TLS verification, resumable caches and conservative byte accounting.
- Optional local catalog search and an experimental listening-association recommendation channel. A mixed five-song batch keeps four audio results and can include one labelled provider discovery. No missing audio features are fabricated.
- Separate licensed-text experiment: 5,797 unique MulJam songs, represented once in persisted sparse TF-IDF indexes. Queries compare saved vectors on demand; no all-pairs table is stored. This measures word/phrase overlap within each language, not validated themes or sound.
- No new audio analysis, paid API, model download, account connection or personal-history upload. Richer sound analysis remains a deferred priority.

The text experiment is not connected to personal recommendations: permitted text for the selected mainstream recordings and verified catalog overlap have not been established. Existing audio features and cached ListenBrainz evidence are the live signals. Fixed bounded weighting is an initial heuristic; improvement still requires held-out user judgments. See [implementation details](ENRICHMENT_IMPLEMENTATION.md).

## Validation

The catalog and text agents implemented their separate components. A third agent reviewed the new code as devil's advocate; identified identity, partial-data and test-timing issues were corrected. Its final review reported no blocking findings. This is a code review, not a security or legal guarantee.

All **47 tests passed** in the final full-suite run (13.7 seconds). Tests include baseline fallback, partial metadata, namesake ambiguity, version labels, exclusions, profile isolation, index persistence and desktop workflows. Production scrolling and widget layout were unchanged. A synthetic animation test now inspects the actual first animation callback rather than desktop-load-dependent progress after an event-loop update.

A real existing `drivers license` favorite produced four audio results and one cached ListenBrainz discovery (`Please Me`, Cardi B / Bruno Mars), demonstrating the integration path. It does not establish recommendation quality or similarity of sound.

Six alternating warm requests on the same loaded engine averaged **131 ms original / 141 ms enriched**, with maxima **150 / 162 ms**. Loading the 200,000-song dataset and optional sidecar took 3.63 seconds in that run. The snapshot had 2,828 catalog entries and 714 edges. Collection was still active; this is a single-machine smoke measurement, not a controlled performance guarantee. Queries and initialization use the app's existing background worker. Text-index building and network acquisition never run inside the desktop. See [raw measurements](enrichment_performance.json).

## Storage interpretation

MulJam source responses totaled **12,880,118 bytes**; retained source, index and report totaled **21,304,638 bytes**. Sixty warm text queries averaged **3.14 ms**, maximum **14.93 ms**, excluding startup/build.

The collector's transfer ledger is an **upper bound**, including conservative reservations for failed/partial responses. It is not a measurement of successful downloaded bytes. Retained files are measured separately. The pilot's 250 MB additional-data allowance remains far below the user's preferred 3–4 GB and absolute 5 GB ceiling. Existing CSV/source artifacts total 279,052,278 bytes; Python environment and unrelated project files are outside that data-artifact subtotal.

## Coverage limitations

Recording MBIDs include live, remix, unofficial and other versions: counts are **recording entries, not unique songs or verified studio-only discographies**. The first pass limits pagination and can encounter provider failures. Source errors and completion flags must be read alongside counts; missing responses do not prove a song is unavailable. Metadata does not supply audio features. Reviewed exact artist names may seed artist associations without establishing recording identity; known collisions disable that fallback, but unseen namesakes remain possible.
