# Revised plan: modern dark desktop and better discovery

October 31, 2026. **Approved and implemented.** The user selected dark charcoal and dark royal blue, overriding the earlier mint accent proposal. This document retains the researched plan and critique; see [delivery notes](MODERN_DESKTOP_DELIVERY.md) for completed work and validation. Research roles: modern_ui_research (design/toolkit), lyrics (recommendation/code research), devils_advocate (independent critique), and primary agent (local evidence and synthesis).

## What worked for James Arthur

The saved Yes-rated “Quite Miss Home” result matched **“drivers license” by Olivia Rodrigo**, at a rich-vector distance of **0.03543**, without an artist bonus. Existing measurements:

| Measurement | Quite Miss Home | drivers license |
|---|---:|---:|
| Energy | .430 | .436 |
| Danceability | .578 | .585 |
| Valence | .156 | .132 |
| Tempo, recorded BPM | 136.824 | 143.874 |
| Acousticness | .608 | .721 |
| Duration | 243.2 seconds | 242.0 seconds |
| Key / mode / meter codes | 10 / 1 / 4 | 10 / 1 / 4 |

Most residual weighted distance came from acousticness and loudness differences. That identifies where the numerical match came from, not which perceptual quality made the user enjoy it. No lyrics, vocal timbre or instrumentation were analyzed. The saved Yes already permits this song to become a positive anchor; the current +.08 prior penalty for additional Yes anchors can limit its influence. Preserve the historical match as a development regression, not a held-out test or a rule requiring romantic songs/James Arthur. It must remain excluded from recommendations once liked. Raw audit: [james_arthur_match_audit.json](james_arthur_match_audit.json).

## Proposed work, in order

### 1. Freeze a baseline and slightly reduce artist preference

Recommendation agent + primary agent:

- Capture fixed favorites, source/vector fingerprints, exclusions, ratings and the current .20 ranking configuration before changes.
- Try **.20 → .18**, a 10% reduction in the artist score adjustment. This remains a strong prior, not a learned optimum. Change no other ranking constant during this comparison.
- Compare top-five overlap, source/artist diversity, anchor distance and which components caused rank changes. Keep a close-cross-artist versus distant-same-artist counterexample.
- Preserve the James Arthur/Olivia historical pair and audit the broader neighborhood for promising cross-artist candidates. Do not tune every feature to one positive.
- Include brief blind candidate comparisons in the later interface: positive/negative taste judgments, familiarity as a separate exclusion, and optional “More like this” focused on a liked anchor. Fixed-parameter reduction is immediate scope after approval; automatic learned weights are a later gate.

### 2. Simplify the common application core without changing outputs

Primary agent, reviewed independently:

- Extract a small application service for search, favorites, recommend, feedback, profiles and history. UI modules display state and invoke actions; they do not implement ranking or SQLite workflows.
- Centralize artist parsing and canonical song identity. Today some paths split on `;`, others on `; `, and artist order/Unicode normalization differs.
- Introduce one immutable, versioned ranking configuration and one score-component record. Preserve raw feature distance, artist adjustment, feedback adjustment, graph support and selection rationale.
- Separate retrieval, scoring, diversity selection and explanation formatting. Reuse one artist/group selector instead of stacking two variants.
- Replace hybrid access to private engine tables/helpers with narrow public interfaces. Keep the original baseline available; avoid rewriting the entire backend or database schema.
- Prove behavior parity under the same configuration before allowing deliberate ranking changes.

### 3. Make cross-artist discovery an explicit, measurable route

Recommendation agent:

- Form a bounded candidate union from local audio neighborhoods, liked artists/collaborations and cached related-artist evidence where recording-to-audio joins are reliable.
- Score every acoustic candidate against individual liked anchors; apply the named artist preference separately, then diversify once.
- Existing rich-mode graph discovery is restricted: graph-only metadata does not enter the normal rich result batch. Do not silently restore incomparable metadata scores as audio similarity. Unknown-audio discoveries remain separately labelled and optional.
- Measure how many candidates actually have graph/recording evidence. Current joins are sparse; do not assume cached graph data improves the whole catalog.
- Compare cross-artist approval independently of same-artist approval. Test whether the Yes-anchor handicap suppresses useful new neighborhoods only after the first artist-weight comparison; do not adjust both at once.
- With enough varied explicit judgments, test a small regularized pairwise reranker against the fixed baseline. Never treat unshown songs, skipped ratings or “Already know it” as taste negatives. Neural training and large new datasets remain later work.

### 4. Approve a modern dark design before replacing the window

UI agent:

- Charcoal surfaces, restrained mint accent, consistent spacing, modern system typography, subtle rounded panels and clear hover/focus states.
- Collapsible left navigation: Discover, Liked songs, History; profile controls below. Compact search across the top, with the main recommendations immediately visible.
- Compact song rows/cards with readable title/artist, clear feedback actions and a contextual “Why this match?” drawer showing anchor and evidence. A small familiar/discovery indicator is a proposed presentation feature, not a fabricated confidence score.
- Keep saved-library search and history easy to reach. Use local abstract/initial tiles initially. Avoid a giant introductory banner and repeated instructional paragraphs.
- Provide narrow/wide layouts, keyboard navigation, visible focus, adequate contrast, restrained transitions and reduced motion.
- Produce one realistic mockup for review before polishing the full interface. No player controls or cover-art acquisition are in scope.

### 5. Build a parallel Qt Quick workflow and earn the switch

UI agent + primary agent:

- Recommended renderer: **PySide6 Essentials + Qt Quick/QML**, using the same Python service, vector artifacts and SQLite model. Keep the current Tk launcher available while validating the replacement.
- Prototype one complete workflow first: load → search → favorite → recommend → rate. Use temporary test data/database, then add profile/history parity.
- Use model-backed visible-row lists; never copy the full 200,000-song catalog into QML. Keep CSV loading, ranking and database operations on workers, with UI-thread result delivery and stale-response handling.
- Check Windows scaling at 100%, 150%, 200%; narrow/wide windows; long metadata; keyboard-only use; scrolling; loading/errors; profile isolation; reset safety; persistence and reopening.
- Proposed gates: visible action feedback within 100 ms during background work, measured smooth scrolling targeting a 60 Hz display, and recommendation timing within 10% of a fresh same-machine baseline. These are acceptance targets, not current measurements or toolkit guarantees.
- If the Qt prototype fails compatibility, size or responsiveness gates, retain the service boundary and use a CustomTkinter redesign as the lower-migration fallback.

## Budget and dependency check

No songs/audio/models or new bulk dataset are proposed. Python is currently 3.14.7; none of the alternative UI frameworks is installed. PyPI currently lists PySide6 Essentials 6.12.0 for Python 3.10–3.15, including the QML/Quick controls needed here. Its Windows x86-64 wheel is 82.2 MB and matching Shiboken is 1.3 MB: approximately **83.5 MB of principal compressed packages**, not installed footprint. Prefer Essentials rather than the all-module metapackage; verify the resolver, hashes, compatibility and applicable open-source module licenses before installation.

Proposed ceilings: 150 MB new dependency download and 500 MB additional installed/cache/temporary space; stop and revise if those cannot be met. Current measured `.venv` is 319.8 MB and `data` is 341.4 MB, excluding Git and other project files. The actual complete footprint must be checked before installation against the user's preferred 3–4 GB / absolute 5 GB ceiling. No paid services or commercial Qt license is proposed; use compatible open-source modules with their notices and terms.

## Evaluation and review gates

The existing 84-test suite is the current regression baseline, not evidence of taste accuracy. Keep service/identity/exclusion/profile/history/vector tests, and add Qt workflow tests alongside Tk during the prototype.

Use fresh, blinded judgments with counts and uncertainty; the James Arthur case is already known development evidence. Keep song identities grouped across aliases, remove held-out likes from training contexts, and distinguish unseen-song testing from time-forward testing. Fit any supervised parameters independently within training splits. Log rank changes and source coverage so improvement cannot be confused with the same-artist prior merely hiding weak discovery. If there are too few labels, report that and keep the fixed model.

The independent reviewer checks both tracks. Release the UI and ranking changes separately so regressions have a clear cause. Keep source/version metadata and a simple way to restore the prior model/launcher. No Git commit or push is included in this approval request.

## Critique and revision record

**Initial draft:** full Qt rewrite, artwork-heavy shelves, simultaneous artist/feature/diversity tuning, immediate pairwise learning and broader graph discovery.

**Critique:** too many changing variables; artwork/runtime size unnecessary; Qt does not guarantee speed; sparse ratings cannot support a credible learned model; one positive cannot establish vocal or thematic preferences; graph metadata lacks comparable acoustic scores; another diversity layer duplicates current penalties.

**Revised plan:** smaller .18 artist experiment first, behavior-preserving shared-core cleanup, evidence-bounded discovery, one dark mockup plus one parallel workflow, measured parity before replacement, and learned weights only after clean independent judgments. No new artwork/data pipeline, no full rewrite, no stacked MMR penalty, no hardcoded James Arthur rule. The primary agent cross-checked the agents' proposals and adopted the independent critique in this revision.

## Primary research consulted

- [Spotify's desktop/web design presentation](https://webplayer.byspotify.com/) and [official desktop layout explanation](https://newsroom.spotify.com/2023-06-20/spotify-desktop-experience-redesign-your-library-now-playing-views-customize/): library/search continuity, compact rows, customizable panels. The latter is a dated design reference, not a claim that every 2026 Spotify screen is identical.
- [Spotify's May 2026 usability update](https://newsroom.spotify.com/2026-05-28/playlist-folders-mobile-queue-controls-updates/): organization and smoother everyday actions; unrelated playback/download features are not added to MusicMatch.
- [Qt Quick performance](https://doc.qt.io/qt-6/qtquick-performance.html), [ListView](https://doc.qt.io/qt-6/qml-qtquick-listview.html), [accessibility](https://doc.qt.io/qt-6/accessible-qtquick.html): worker separation, profiling, visible delegates and accessibility metadata.
- [Qt licensing](https://doc.qt.io/qt-6/licensing.html), [Essentials package](https://pypi.org/project/PySide6-Essentials/), [Shiboken package](https://pypi.org/project/shiboken6/): supported runtime, principal wheel sizes and open-source licensing scope.
- [CustomTkinter appearance](https://customtkinter.tomschimansky.com/documentation/appearancemode/) and [scaling](https://customtkinter.tomschimansky.com/documentation/scaling/): fallback option; [pywebview Windows installation](https://pywebview.flowrl.com/guide/installation) was considered but adds a browser bridge/runtime not required by this plan.
- [Google recommendation reranking](https://developers.google.com/machine-learning/recommendation/dnn/re-ranking) and [Rules of ML](https://developers.google.com/machine-learning/guides/rules-of-ml): separate selection objectives, measured simple changes and robust infrastructure before complexity.
- [Joachims preference ranking paper](https://www.cs.cornell.edu/people/tj/publications/joachims_02c.pdf): a future pairwise method, not evidence of MusicMatch quality. [MMR paper](https://www.cs.cmu.edu/afs/cs/Web/People/jgc/publication/MMR_DiversityBased_Reranking_SIGIR_1998.pdf) informed diversity review; deferred to avoid stacking selectors.
- [scikit-learn evaluation guidance](https://scikit-learn.org/stable/modules/cross_validation.html): independent evaluation; [ListenBrainz API](https://listenbrainz.readthedocs.io/en/latest/users/api/core.html): scope of cached related-artist candidate evidence.
- [W3C contrast guidance](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html): target 4.5:1 ordinary text and 3:1 large text.
