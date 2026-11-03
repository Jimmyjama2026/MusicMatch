"""UI-independent application actions; callers serialize them on a worker.

Constructing the service is cheap. initialize() loads the library and profile.
All returned values are plain JSON-compatible snapshots, not live DB objects.
"""
from __future__ import annotations

if __package__:
    from .backend import FeedbackStore
    from .hybrid import MusicRecommender
    from .identity import credited_artists, artist_ids
    from .neighborhood_view import attach_visuals, empty_view
    from .title_language import TitleLanguageScreen
    from .preference_policy import validate_steering
    from .neural_manager import NeuralTrainingManager
else:
    from backend import FeedbackStore
    from hybrid import MusicRecommender
    from identity import credited_artists, artist_ids
    from neighborhood_view import attach_visuals, empty_view
    from title_language import TitleLanguageScreen
    from preference_policy import validate_steering
    from neural_manager import NeuralTrainingManager


class ApplicationService:
    def __init__(self, engine=None, store=None, language_screen=None, learning_manager=None):
        self.engine = engine
        self.store = store
        self.language_screen = language_screen
        self.learning_manager = learning_manager
        self.profile_id = None
        self._visible_songs = {}

    def initialize(self):
        if self.engine is None:
            self.engine = MusicRecommender()
        if self.store is None:
            self.store = FeedbackStore()
        if self.language_screen is None:
            self.language_screen = TitleLanguageScreen(self.store.path.parent / "sources" / "title_language.sqlite3")
        if self.learning_manager is None:
            self.learning_manager = NeuralTrainingManager(self.store.path.parent / "sources" / "neural_models")
        self.profile_id = self.store.get_active_profile()
        return self.current_state(message="Your library is ready.")

    def _ready(self):
        if self.engine is None or self.store is None or self.profile_id is None:
            raise RuntimeError("The library is still loading.")

    def _remember(self, songs):
        self._visible_songs.update((song["track_id"], dict(song)) for song in songs)
        # Cache is only a fallback for historical songs no longer in the catalog.
        if len(self._visible_songs) > 2000:
            self._visible_songs = dict(list(self._visible_songs.items())[-1000:])

    def _song(self, track_id):
        self._ready()
        try:
            return self.engine.get_song(track_id)
        except ValueError:
            if track_id in self._visible_songs:
                return dict(self._visible_songs[track_id])
            raise

    def current_state(self, message=""):
        self._ready()
        state = self.store.load_profile(self.profile_id)
        # New language policy applies to the active suggestion view immediately.
        # The stored batch and explicitly opened history remain immutable.
        with self.language_screen.session():
            state["recommendations"] = [song for song in state["recommendations"]
                                        if self.language_screen.allows(song)]
        profiles = self.store.list_profiles()
        self._remember(state["favorites"] + state["recommendations"])
        audio = getattr(self.engine, "audio", self.engine)
        warning = getattr(audio, "vector_warning", None)
        if warning:
            model_status = "Original audio model · rebuild local vectors for neighborhoods"
        elif getattr(audio, "vectors_active", False):
            model_status = "Preference neighborhoods · artist-aware matching"
        else:
            model_status = "Local audio matching"
        state.update(profiles=profiles, profile_id=self.profile_id,
                     profile_name=next(p["name"] for p in profiles if p["id"] == self.profile_id),
                     counts=list(state["counts"]), model_status=model_status, message=message)
        state["neighborhood_view"] = next((s["neighborhood_visual"] for s in state["recommendations"]
            if "neighborhood_visual" in s), empty_view(
                "This saved batch predates neighborhood visuals. Request new suggestions to see its current neighborhoods."
                if state["recommendations"] else "Generate suggestions to see the neighborhoods used for that batch."))
        state.update(self.store.comparison_state(self.profile_id, state["batch_id"]))
        pair = state.get("comparison")
        if pair:
            with self.language_screen.session():
                if not all(self.language_screen.allows(pair[key]) for key in ("a", "b")):
                    state["comparison"] = None
        state["title_screening"] = "English-only title screening"
        vectors = getattr(audio, "vectors", None)
        state["learning_status"] = self.learning_manager.observe(self.store.path, self.profile_id,
            vectors.metadata if vectors is not None else None)
        return state

    def search(self, title, artist="", title_only=True):
        self._ready()
        songs = self.engine.search(str(title), str(artist), bool(title_only))
        self._remember(songs)
        return songs

    def add_favorite(self, track_id):
        state = self.current_state()
        if track_id not in {s["track_id"] for s in state["favorites"]}:
            song = self._song(track_id)
            vectors = getattr(getattr(self.engine, "audio", self.engine), "vectors", None)
            if vectors is not None:
                song = dict(song, feature_version=vectors.metadata["version"],
                            source_fingerprint=vectors.metadata["source_fingerprint"])
            self.store.save_favorites(self.profile_id, state["favorites"] + [song])
        return self.current_state(message="Added to your liked songs.")

    def remove_favorite(self, track_id):
        state = self.current_state()
        self.store.save_favorites(self.profile_id, [s for s in state["favorites"] if s["track_id"] != track_id])
        return self.current_state(message="Removed from your liked songs.")

    def recommend(self, fresh=False, focus_track_id=None, steering="same"):
        validate_steering(steering)
        if not focus_track_id and steering != "same":
            raise ValueError("Choose a song with More like this to steer this request.")
        state = self.current_state()
        active_favorites = state["favorites"]
        selected = [self._song(focus_track_id)] if focus_track_id else active_favorites
        if not selected:
            raise ValueError("Add at least one liked song before asking for suggestions.")
        favorites = [self._song(song["track_id"]) for song in selected]
        feedback = self.store.training_feedback(self.profile_id)
        known_artist_names = set().union(*(credited_artists(song) for song in
            active_favorites + [item for item in feedback if item["liked"]]))
        known_artist_ids = set().union(*(artist_ids(song) for song in
            active_favorites + [item for item in feedback if item["liked"]]))
        exclusions = self.store.recommendation_exclusions(self.profile_id, fresh=bool(fresh))
        exclusions.update(s["track_id"] for s in active_favorites)
        exclusions.update(s["track_id"] for s in feedback if s["liked"])
        if focus_track_id:
            # A focused request follows this anchor; other Yes neighborhoods
            # must not quietly replace it. Dislikes still constrain the result.
            feedback = [s for s in feedback if not s["liked"]]
        with self.language_screen.session():
            songs = self.engine.recommend([s["track_id"] for s in favorites],
                favorite_songs=favorites, feedback=feedback, exclude_ids=exclusions,
                known_artist_names=known_artist_names, known_artist_ids=known_artist_ids,
                steering=steering, pairwise_feedback=self.store.training_comparisons(self.profile_id),
                candidate_filter=self.language_screen.allows)
            for song in songs:
                song["title_language"] = self.language_screen.screen(song)
        if songs:
            audio = getattr(self.engine, "audio", self.engine)
            attach_visuals(songs, getattr(audio, "vectors", None))
            if focus_track_id:
                for song in songs:
                    song["focused_on"] = {"track_id": focus_track_id,
                                          "track_name": favorites[0]["track_name"],
                                          "artists": favorites[0]["artists"]}
            batch_id = self.store.save_batch(favorites, songs, self.profile_id,
                active_favorites=active_favorites if focus_track_id else None)
            self.store.offer_comparison(self.profile_id, batch_id)
        else:
            self.store.clear_current_recommendations(self.profile_id)
        if not songs:
            message = "No eligible unseen English matches were found. Adjust Fresh suggestions or review your history." if fresh else "No eligible English matches were found for these likes."
        elif focus_track_id:
            message = f"Suggestions focused on {favorites[0]['track_name']} ({steering.replace('_', ' ')}); your liked list is unchanged."
        else:
            message = "Your suggestions are ready. Tell us which ones fit."
        if songs:
            context = songs[0].get("selection_context", {})
            requested = context.get("discovery_requested", 0)
            if requested:
                message += f" {context.get('discovery_fulfilled', 0)} of {requested} new-artist discovery slots filled."
                if context.get("discovery_shortfall"):
                    message += " Not enough suitably close, distinct new artists remained; other matches fill the list."
        return self.current_state(message=message)

    def more_like_this(self, track_id, fresh=False, steering="same"):
        return self.recommend(fresh=fresh, focus_track_id=track_id, steering=steering)

    def choose_comparison(self, comparison_id, choice):
        self._ready()
        self.store.choose_comparison(self.profile_id, comparison_id, choice)
        return self.current_state(message="Comparison saved. It affects future suggestions; no song was marked disliked.")

    def undo_comparison(self, comparison_id):
        self._ready()
        self.store.undo_comparison(self.profile_id, comparison_id)
        return self.current_state(message="Comparison undone. Future suggestions no longer use that choice.")

    def reset_comparisons(self):
        self._ready()
        self.store.reset_comparisons(self.profile_id)
        return self.current_state(message="This profile's comparisons were cleared. Likes and Yes/No feedback are unchanged.")

    def set_title_language(self, track_id, language):
        self._ready()
        self._song(track_id)  # Reject unknown IDs rather than save a mistyped correction.
        self.language_screen.set_override(track_id, language)
        return self.current_state(message="Title-language correction saved for this song across profiles. New requests use it; saved history is unchanged.")

    def rate(self, batch_id, track_id, liked, reason=None):
        self._ready()
        self.store.save_feedback(batch_id, track_id, liked, self.profile_id, reason=reason or None)
        result = self.current_state(message="Your feedback is saved.")
        # The rated history batch can differ from the current batch.
        result["rated_batch"] = self.load_history(batch_id)
        return result

    def switch_profile(self, profile_id):
        self._ready()
        self.store.set_active_profile(profile_id)
        self.profile_id = profile_id
        self._visible_songs.clear()
        return self.current_state(message="Profile switched.")

    def reset_test(self):
        self._ready()
        if self.profile_id != "test":
            raise ValueError("Only the Test profile can be reset.")
        self.learning_manager.reset("test")
        self.store.reset_profile("test")
        self._visible_songs.clear()
        return self.current_state(message="Test profile reset. Personal data is preserved.")

    def list_history(self, rating="all", limit=30, offset=0):
        self._ready()
        return [dict(row, count=row["recommendation_count"]) for row in
                self.store.list_history(self.profile_id, str(rating).lower(), limit, offset)]

    def load_history(self, batch_id, rating="all"):
        self._ready()
        result = self.store.load_batch(self.profile_id, batch_id, str(rating).lower())
        self._remember(result["favorites"] + result["recommendations"])
        return result

    def close(self):
        # FeedbackStore opens and closes a connection per action.
        self._visible_songs.clear()
        if self.learning_manager is not None:
            self.learning_manager.close()
