# Artist preference update

October 31, 2026. The user explicitly requested substantially more artist weight after numerical neighbors remained poor matches.

The rich model is now `rich-neighborhoods-artist-v2` (`rich-neighborhoods-artist-listening-v2` when the hybrid evidence route is used). Each candidate/liked-anchor comparison receives a **0.20 score reduction** when they share at least one credited artist. This is a fixed distance-unit adjustment, not a percentage or learned optimum. It applies before anchor selection and shortlisting, so favorite-artist songs can enter the results even when unrelated songs have slightly closer audio measurements. Raw feature distance and artist adjustment are stored separately.

Artist IDs from the existing CSV take precedence when both records have usable IDs. Exact normalized credited names are used when IDs are unavailable; fuzzy/substring name matches are not used. Collaborators count, but multiple matching collaborators do not multiply the boost. A cached artist-to-row index is prepared during background library loading rather than scanning credit strings on every query. No vector rebuild, CSV changes, download or dependency installation is needed.

Neighborhood diversification and the soft cap of two songs per credited artist remain. Favorites, No votes and requested Fresh history stay excluded. Unicode/apostrophe variants of a favorite's title are now excluded before shortlisting so a duplicate cannot consume an artist slot. Unknown-artist candidates remain eligible; this is a preference weight, not an artist-only filter. Existing baseline fallback behavior remains unchanged.

This update adds regressions for artist preference outranking a closer unrelated numeric match, stable IDs overriding misleading names, exact names avoiding substring matches, collaborator overlap, exclusions, and favorite-title punctuation aliases. See `artist_weight_report.json` for the local saved-favorites diagnostic. Actual user preference improvement still needs testing; related-artist/genre/language understanding has not been added.

In the six-saved-favorites diagnostic with 35 Fresh exclusions, the weighted results promoted `KMT` (Drake/Giggs), `Sneakin’` (Drake/21 Savage) and `Wondering` (Olivia Rodrigo/Julia Lester). Two other artists remained eligible through numerical matching. The diagnostic used no rating feedback and read the actual database without writing it. One warm query took 154 ms; this is not a latency guarantee. Artist preference and raw distance are visible separately in the saved report.

The favorite-alias regression also exposed pandas/NumPy discarding the old NUL string separator while Python exclusion keys retained it. Rich-neighborhood identity keys now use a consistent non-NUL separator, with apostrophe normalization, so favorite aliases are suppressed before artist caps and shortlisting.
