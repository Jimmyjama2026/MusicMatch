# Liked songs count as training Yes judgments

Adding a song to Liked songs is now an explicit positive training judgment for both
the neural model and its logistic-regression comparison. It does not create a fake
recommendation batch, change past votes, or enable either model in live ranking.

## Identity and conflicts

The read-only training export combines current liked songs with recommendation
votes, deduplicated by normalized title and full artist credits. A song present in
both contributes one judgment. Favorite add times come from the existing favorite
event history; the most recent explicit action wins when it conflicts with a vote.
Feedback wins exact timestamp ties, since independent event-table sequence values
cannot establish ordering across action types.

Removing a favorite withdraws its standalone positive contribution; it is not a No.
A separate recommendation vote can still contribute. Profiles remain isolated.
Older current favorites without an add event retain an explicitly identified
first-observed-batch timestamp, or an unknown-time sentinel when no batch exists;
the exporter does not claim these are their original addition times.

New additions preserve audio feature versions, source fingerprints and available
genre evidence. Previously unversioned favorite snapshots are usable only after
their ID, title/full credits and all saved raw measurements match the current
catalog, and the current feature manifest matches the production vector source.
The resolver records this provenance in the exported record without writing it to
historical data. It does not backfill genre labels. Missing measurements still make
an example unusable; selecting a metadata-only recording cannot invent its audio.

## Search-added likes have no recommendation anchor

They enter as positive song-level examples with explicitly missing anchor context.
No song is used as its own anchor. Anchor coordinates, difference coordinates and
anchor-genre coordinates are masked, and anchor coverage indicates missing context.

When favorites are included, training also adds masked-anchor views of contextual
training examples from **both** Yes and No classes. This prevents the mere absence
of an anchor from being an exclusively positive cue. These views are generated
after the held-out identity split, only from training songs; they do not inflate the
distinct-judgment counts. Class balancing and normalization use the augmented
training set only. Held-out songs and their anchor-purge protection remain separate.

The model stays at 284 inputs and 4,577 parameters. Its version is now
`contextual-shadow-mlp-v3-favorite-positives`, rejecting incompatible older artifacts.
Readiness remains 100 usable distinct songs, at least 20 in each class and three
artist families. For an anchorless positive, the candidate's credited artist family
supplies the family-diversity check. Automatic model promotion remains disabled.

## Validation

The existing Test profile was inspected read-only after this change: **153 usable
distinct judgments, including 83 Yes and 70 No**. Of those, **38 positive records**
come from current liked songs rather than recommendation votes. Other favorite/Yes
overlaps remain deduplicated. No feedback, favorite list, model artifact or
recommendation history was changed during the audit.

Tests cover favorite positives without self-anchors, duplicate Yes handling, later
No corrections, removal neutrality, profile isolation, anchorless model inference,
and both label classes in masked training views. The full suite passed 204 tests.

Restart MusicMatch to load the change. A ready profile is eligible for a new shadow
training attempt because the model contract changed; its existing debounce and
worker limits still apply. The prior model's evaluation score does not describe
this new training dataset or architecture behavior.
