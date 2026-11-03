# MusicMatch coverage audit — October 30, 2026

Status: local historical coverage checked; current MusicBrainz and AcousticBrainz coverage remains unverified because API requests could not connect. No dataset archives downloaded and no active catalog changes made.

## Counts

Artist matching uses exact normalized credited names. Counts include collaborations and distinct versions; they are not complete current discographies. Namesakes require artist-ID verification. Data ends in early 2021.

| Artist | Active catalog | Already cached source | Additional |
|---|---:|---:|---:|
| Olivia Rodrigo | 5 | 5 | 0 |
| Tate McRae | 11 | 11 | 0 |
| Justin Bieber | 110 | 124 | 14 |
| NF | 35 | 35 | 0 |
| Luke Combs | 26 | 26 | 0 |
| Zach Bryan | 1 | 1 | 0 |
| Bailey Zimmerman | 0 | 0 | 0 |
| Halsey | 29 | 29 | 0 |
| Doja Cat | 22 | 22 | 0 |
| Dua Lipa | 34 | 40 | 6 |
| Drake | 209 | 209 | 0 |
| Bad Bunny | 143 | 144 | 1 |
| Metro Boomin | 15 | 15 | 0 |
| Plain White T’s | 4 | 4 | 0 |
| Morgan Wallen | 38 | 38 | 0 |
| Khalid | 39 | 40 | 1 |
| Bruno Mars | 54 | 54 | 0 |
| Kanye West | 162 | 162 | 0 |
| Riley Green | 2 | 2 | 0 |
| Noah Kahan | 6 | 6 | 0 |
| Taylor Swift | 192 | 193 | 1 |
| Coldplay | 67 | 69 | 2 |
| Imagine Dragons | 46 | 47 | 1 |
| Jack Johnson | 68 | 68 | 0 |
| Benson Boone | 0 | 0 | 0 |
| Jordan Davis | 4 | 4 | 0 |
| Post Malone | 50 | 51 | 1 |

Deduplicated across selected artists: 1358 active; 1384 cached; 26 additional. Collaborations can appear under multiple artists above.

## Storage decision

- Existing dataset, backup and source ZIP: 279,052,278 bytes (0.279 GB decimal). Python environment excluded.
- Reusing cached source: 0 bytes of new source download. Only 26 additional matching historical recordings found.
- Current artist metadata plus selected features: reserve 100–250 MB as a conservative planning allowance, NOT a measured provider transfer size.
- Compact AcousticBrainz feature archives: server lists 1G + 1G + 843M (approximately 3 GB compressed). Those contain global data; no verified artist-specific coverage yet.
- Full JSON archive sizes: not measured, not approved for download.
- Prior 5 GB working-space estimate is conditional on streaming and is not a verified peak-use guarantee.
- Preferred total downloaded-data storage 3–4 GB; absolute 5 GB including existing source files and temporary/extracted data. No bulk download until a specific plan is reviewed.

## Sources

- https://musicbrainz.org/doc/MusicBrainz_API
- https://acousticbrainz.readthedocs.io/api.html (count endpoint can check availability without fetching full feature records)
- https://data.metabrainz.org/pub/musicbrainz/acousticbrainz/dumps/acousticbrainz-lowlevel-features-20220623/

Next: obtain current recording IDs and check AcousticBrainz counts, then measure targeted transfer sizes. Current online coverage cannot be inferred from local historical counts.
