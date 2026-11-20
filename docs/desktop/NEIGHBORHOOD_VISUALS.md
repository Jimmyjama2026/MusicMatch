# Neighborhood visuals and artist discovery

Implemented locally after the charcoal/royal-blue desktop round.

## What changed

- **Neighborhoods** tab shows the actual anchors and groups used for the latest
  saved suggestion batch. Dots represent liked/Yes anchors, diamonds suggestions;
  click a point or use Tab/Enter to identify the song and group.
- **Why this match?** highlights that suggestion in the saved map, names its actual
  matched anchor and shows raw feature pairs: energy, valence, danceability,
  acousticness, recorded tempo, duration and artist evidence. Technical explanation
  remains expandable. Missing/invalid measurements display as unavailable.
- Normal requests for five songs reserve **two slots** for suitably close artists
  outside all active favorites and positive ratings. Full collaborator credits and
  known provider IDs count, including during focused requests. The two discoveries
  must also have distinct artist names/IDs from each other. Discovery badges and
  fulfilled-slot counts explain the selection.

## Exact policy and limits

Artist adjustment stays .18. The discovery policy is a selection constraint,
not another blanket weight reduction or random exploration. Discovery candidates
must have rich shared-feature distance at most .10; dedicated retrieval prevents
the artist boost from hiding them before selection. If fewer than two suitable,
distinct unfamiliar artists remain, the list uses other eligible matches and
reports the shortfall. This quota applies to requested batches of at least five;
smaller diagnostic requests retain their ranking. Legacy/metadata-only routes
explicitly report that reliable rich-distance evidence is unavailable.

Discovery means outside the saved liking context, not proof the user has never
heard that artist. Similarity still does not establish language, genre, vocal or
lyrical similarity. The historical international catalog is unchanged.

## Honest, bounded visuals

Ranking remains in the existing 21-dimensional space. A local PCA/SVD projection
is fitted to at most 96 actual anchor representatives plus the returned songs,
on the serialized recommendation worker. It uses a common display scale, fixes
axis signs and handles constant/single-point cases. Missing vectors are not
plotted as zeros. At most 64 dots are shown; suggestions and their matched anchors
take priority. Omitted counts are explicit.

Colors use actual ranking group IDs, not clusters inferred from the drawing.
Two-dimensional closeness can hide important differences; axes fitted to one
batch cannot be compared with another batch. No boundary circles imply a false
ranking radius. Maps and comparison tables are saved before the batch write,
so history keeps the original explanation even after preferences/features change.
Older batches without maps say so and remain usable. Minimal whitelisted anchor
snapshots prevent recursive embedding of earlier recommendation histories.

## Verification

Full suite: **121 tests passed**. Additional checks cover two unfamiliar slots,
collaborators, provider aliases, focused full-profile artist context, shortages,
retrieval beyond same-artist leaders, minimal anchor snapshots, real vector
projection, incomplete/invalid data, bounded dots, immutable history and keyboard
navigation of the actual Qt map/table. The seven Qt checks passed again after
the compact detail-map refinement.

Independent review caught and resolved two issues: artist aliases from nonfocused
collaborations needed full known-ID context, and finite-but-invalid measurements
needed explicit table validation. Wide/narrow maps and explanations were rendered
using a disposable copy of the real database, with no Qt warnings. Tests and
preview do not modify the user's original database.

Frozen six-favorite context requests with the quota took 221–245 ms. A subsequent
real desktop previews used the user's expanded 20-favorite context; end-to-end
requests took about 515–847 ms and their longest recommendation-phase event-loop
timer gaps were 25–30 ms. These contexts differ and are not a matched speed comparison.
Physical display frame rate remains unverified. Reproduce with
`python scripts/preview_desktop.py --output data/sources/neighborhood_preview`.

No new dependency, model, bulk catalog or audio download was needed. No commits or
pushes were made. Useful future work: one-click familiarity feedback separate from
taste rejection, and a user control for one versus two discovery slots.
