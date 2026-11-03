# MusicMatch data acquisition proposal

Original proposal reviewed October 30, 2026. Implementation has since been approved and started. This document preserves the planning estimates and initial connectivity findings; see [ENRICHMENT_IMPLEMENTATION.md](ENRICHMENT_IMPLEMENTATION.md) for the implemented behavior and [ENRICHMENT_RUN_REPORT.md](ENRICHMENT_RUN_REPORT.md) for measured acquisition results.

## Policy findings

- MusicBrainz core recording, artist, release and identifier metadata is CC0. The public API is free for noncommercial use, requires an identifying User-Agent, and permits at most one call per second. Supplementary tags, ratings and annotations have a separate CC BY-NC-SA license; omit those from the first pass.
- ListenBrainz's own public listen dataset is CC0. MetaBrainz explicitly describes studying consumption patterns and recommendation engines as uses. Prefer targeted aggregate/recommendation requests over full dumps or identifiable user histories. Do not assume every third-party dataset or external link surfaced by the service shares that license.
- LRCLIB permits anonymous API access and documents library-scanning clients. No clear underlying-lyrics license for bulk storage, analysis, redistribution or training was established. MIT covers its server code, not the songwriters' lyrics. Personal/noncommercial use does not automatically establish fair use. Keep bulk LRCLIB lyric acquisition outside the approved-source proposal until rights are established.
- MulJam authors publish their lyrics transcription dataset under CC BY-NC-SA in the paper. Attribute creators, preserve notices, keep use noncommercial, mark modifications, and apply applicable ShareAlike terms when sharing adapted data. Record the exact license/version provided with the chosen distribution before acquisition. Do not label the material public domain. Jamendo research corpus coverage is distinct from the user's mainstream artist catalog.
- Existing Kaggle source has a recorded CDLA-Sharing-1.0 publisher license. Preserve provenance and notices; it is not independent verification of upstream Spotify rights. Do not silently expand that source into a new ML training corpus based on the publisher label alone.

## Proposed acquisition

1. Resolve the 27 selected artists to MusicBrainz IDs, manually verifying ambiguous names. Collect official studio albums, bonus tracks and singles first, then credited collaborations. Store recording IDs, artist credits, titles, release references/dates, durations and ISRCs where present. Target an initial ceiling of 10,000 deduplicated recordings, not a claim of available coverage.
2. MusicBrainz connectivity retest succeeded: an artist lookup returned HTTP 200 and JSON. ListenBrainz still fails during TLS negotiation in both Python and Windows curl, before an HTTP response. The exact network cause is unconfirmed; the error is not an authentication, billing or license rejection. No paid account or key is needed for public MusicBrainz reads; ListenBrainz authentication varies by endpoint, with a free account token where required.
3. Obtain targeted ListenBrainz aggregate popularity and recommendation relationships for matched IDs. Target up to 100,000 relationships; actual available coverage and per-result provenance must be checked. Do not download the full listen dump. Store IDs, source counts/scores, algorithm/time context and retrieval dates; avoid retaining individual users' histories.
4. Separately obtain a single licensed MulJam text distribution for lyric-matching development, after checking its distribution notices. Do not download audio or rerun its GPT-based transcription pipeline. Its repository describes 6,031 source songs; derived versions and duplicate test files are not additional songs. Coverage of the user's favorite artists is not established.

## Storage and transfer budget (decimal units)

| Item | Planning allowance |
|---|---:|
| Targeted MusicBrainz metadata | 25 MB |
| Targeted ListenBrainz records | 50 MB |
| One MulJam text distribution | 15 MB |
| Local database, sparse text features, indexes and notices | 60 MB |
| Temporary files and headroom | 100 MB |
| Total additional peak storage allowance | 250 MB |

The original MulJam directory contains 8,689,464 bytes across 6,071 non-.DS_Store files. MulJam_v2.0 contains 12,974,682 bytes across 77 files. These are file payload sizes measured from GitHub's tree manifest, not ZIP transfer sizes, filesystem allocation or counts of unique songs. Download one distribution only. See lyrics_dataset_size_audit.json for pinned revision.

Existing dataset CSV, original backup and source ZIP total 279,052,278 bytes. Proposed existing-plus-new data allowance is approximately 529 MB (0.53 GB). Other current project files add little, but the Python environment is excluded; no new models, dependencies, or audio are proposed. Provider response sizes and exact retained totals are not yet measured; the table is a bounded acquisition design, not a quote.

The future downloader should track cumulative response bytes (including retries), stored bytes and temporary copies; stream responses with per-response caps; leave headroom for network overhead and filesystem allocation; stop on budget exhaustion; honor Retry-After and provider limits. Keep additional retained-plus-temporary data below 250 MB and separately cap API/dataset response payloads below 225 MB. This is much stricter than the user's preferred 3–4 GB and absolute 5 GB total downloaded-data storage ceiling. Re-budget explicitly before expanding.

## Use of the data

- Match IDs and versions before merging, retain provenance and unknown fields, and produce per-artist coverage counts.
- Add a recommendation route that can use listener relationships for tracks lacking acoustic measurements. Preserve distinctions between listening association and sound similarity.
- On licensed text, start with TF-IDF and cosine similarity using existing scikit-learn. This compares distinctive word patterns; it is not reliable deep thematic understanding, especially for negation, metaphor or cross-language comparisons. Evaluate separately by language and do not equate shared words with the same meaning.
- Compare suggestions against the current four-feature baseline using held-out/new Yes/No feedback. Report observed improvement rather than promising it. Prevent evaluation leakage and avoid inferring dislikes from missing listens.
- Keep the experimental Jamendo lyric corpus separate from the personal artist catalog unless actual matching establishes overlap. Richer lyric analysis for mainstream favorites remains contingent on permitted text.

## How API retrieval works

MusicMatch sends a small HTTPS GET request with an artist or recording identifier and query parameters. The provider replies with JSON: structured text fields. Python parses it, checks the response and identity, retains only useful fields in local SQLite and records source/license/retrieval time. Pages are requested sequentially; cached results prevent repeated calls. HTTP 429 means slow down, 503 means retry later, and neither means a song is absent. No audio playback, account surveillance or model training happens simply because an API request is sent.

## Sources

- https://metabrainz.org/datasets/postgres-dumps
- https://musicbrainz.org/doc/MusicBrainz_API
- https://listenbrainz.readthedocs.io/en/latest/users/api/index.html
- https://lrclib.net/docs.txt
- https://github.com/tranxuanthang/lrclib/issues/111
- https://arxiv.org/abs/2306.17103
- https://github.com/zhuole1025/LyricWhiz
- https://creativecommons.org/publicdomain/zero/1.0/
- https://www.copyright.gov/fair-use/more-info.html

## Additional US-law review

Explicit source permission is the recommended basis for the catalog/listening-data plan. It does not require a fair-use defense for the licensed use. MetaBrainz's account page explicitly includes personal use and university course assignments in its $0 noncommercial tier: https://metabrainz.org/supporters/account-type

17 USC 106 reserves reproduction and derivative-work rights subject to exceptions. Section 107 balances purpose (including noncommercial/educational purpose), nature, amount, and market effect. Purely local noncommercial use is relevant and favorable to part of that analysis, but is not a blanket exemption for copyrighted lyrics. This review assumes US law; it is an evidence-based assessment, not a guarantee of a court outcome.

Relevant decisions inspected:

- Feist Publications v. Rural Telephone, 499 US 340 (1991): facts are not copyrightable, though an original compilation can be. Supports distinguishing factual metadata from creative lyrics; does not waive contracts or other rights. https://www.govinfo.gov/content/pkg/USREPORTS-499/pdf/USREPORTS-499-340.pdf
- Authors Guild v. HathiTrust, 755 F.3d 87 (2d Cir. 2014): full-text search of digitized books was fair use under the facts before the court. Supports non-substitutive computational uses by analogy, not a categorical lyrics ruling. https://www.govinfo.gov/content/pkg/USCOURTS-ca2-12-04547/pdf/USCOURTS-ca2-12-04547-0.pdf
- Authors Guild v. Google, 804 F.3d 202 (2d Cir. 2015): digitization for search and constrained snippets was fair use under the facts before the court. https://ww3.ca2.uscourts.gov/decisions/OPN/13-4829_opn.pdf
- Andy Warhol Foundation v. Goldsmith, 598 US 508 (2023): a new meaning/message alone does not settle the first fair-use factor; the specific challenged use matters. https://www.supremecourt.gov/opinions/22pdf/21-869_87ad.pdf
- Bartz v. Anthropic, ND Cal., June 23, 2025, docket 231: the order found the training use fair but did not justify acquisition/retention of pirated books for a central library on that basis. A fact-specific district-court order, not a nationwide blanket permission for AI training or LRCLIB. https://docs.justia.com/cases/federal/district-courts/california/candce/3:2024cv05417/434709/231

For local lyric-pattern analysis, a different analytical purpose, no public text display, and no commercial service support a fair-use argument. Creative lyrics, copying entire texts, source authorization, and any market substitution remain considerations. No decision inspected directly adjudicates this exact LRCLIB-plus-local-recommender workflow. Therefore, do not label bulk mainstream lyric acquisition confirmed lawful based solely on private use or these analogies. It is also not established unlawful merely because a license is unverified.
