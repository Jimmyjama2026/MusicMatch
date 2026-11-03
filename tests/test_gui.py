"""Exercise real Tk widgets and asynchronous callbacks without a visible window."""
import tempfile
import time
import json
import tkinter as tk
import unittest
import pandas as pd
from pathlib import Path
from unittest.mock import patch
from unittest.mock import Mock
from types import SimpleNamespace

from data.backend import FeedbackStore
from data.hybrid import MusicRecommender as HybridRecommender
from data.main import MusicMatchApp


class DemoEngine:
    favorite = {"track_id": "a", "track_name": "Favorite", "artists": "Artist", "energy": .5}
    suggestion = {"track_id": "b", "track_name": "Suggestion", "artists": "Other", "energy": .51,
                  "reason": "Similar energy to your favorites.", "distance": .01, "model_version": "test"}

    def search(self, query, artist_query="", title_only=False):
        return [dict(self.favorite)]

    def get_song(self, track_id):
        return dict(self.favorite)

    def recommend(self, ids, favorite_songs=None, feedback=None, exclude_ids=None):
        return [] if "b" in (exclude_ids or []) else [dict(self.suggestion)]


class DesktopTests(unittest.TestCase):
    @staticmethod
    def descendants(widget):
        for child in widget.winfo_children():
            yield child
            yield from DesktopTests.descendants(child)

    def test_mapped_window_geometry_with_long_song_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = FeedbackStore(Path(temporary) / "geometry.sqlite3")
            root = tk.Tk()
            root.withdraw()
            app = None
            try:
                with patch("data.main.MusicRecommender", return_value=DemoEngine()), patch("data.main.FeedbackStore", return_value=store):
                    app = MusicMatchApp(root)
                    self.wait(root, app)
                song = dict(DemoEngine.suggestion, track_name="A remarkably long song title with many words " * 7,
                            artists="An artist with a very long name and collaborators " * 5,
                            liked=False, feedback_reason="Wrong mood")
                app.show_matches([song])
                app.favorites = {song["track_id"]: song}
                app.render_favorites()
                app.show_recommendations(("geometry", [song]), scroll=False)
                app.toggle_details(app.recommendation_views[0])
                app.toggle_history()
                self.wait(root, app)
                root.deiconify()
                for geometry, mode in (("560x650", "stacked"), ("1100x800", "columns")):
                    root.geometry(geometry)
                    for _ in range(5):
                        root.update()
                        root.update_idletasks()
                    self.assertEqual(app.layout_mode, mode)
                    self.assertLessEqual(abs(app.page.winfo_width() - app.canvas.winfo_width()), 1)
                    for panel in (app.search_panel, app.favorites_panel):
                        self.assertGreaterEqual(panel.winfo_rootx(), app.body.winfo_rootx() + 28)
                        self.assertLessEqual(panel.winfo_rootx() + panel.winfo_width(), app.body.winfo_rootx() + app.body.winfo_width() - 28)
                    for label in self.descendants(app.page):
                        if not isinstance(label, tk.ttk.Label) or not label.winfo_ismapped():
                            continue
                        parent = label.master
                        padding = parent.tk.splitlist(parent.cget("padding")) if "padding" in parent.keys() else ()
                        values = [parent.winfo_pixels(str(value)) for value in padding]
                        left = values[0] if values else 0
                        right = values[2] if len(values) >= 3 else left
                        self.assertGreaterEqual(label.winfo_x(), left, label.cget("text"))
                        self.assertLessEqual(label.winfo_x() + label.winfo_width(), parent.winfo_width() - right, label.cget("text"))
                    self.assertEqual(sum(isinstance(widget, tk.Canvas) for widget in self.descendants(root)), 1)
                    expanded_height = app.favorites_panel.winfo_height()
                    app.toggle_favorites()
                    root.update()
                    self.assertLess(app.favorites_panel.winfo_height(), expanded_height)
                    app.toggle_favorites()
                    root.update()
            finally:
                if app:
                    app.close()
                else:
                    root.destroy()

    def test_scroll_accumulates_small_deltas_and_ignores_outside(self):
        canvas = Mock()
        fake = SimpleNamespace(root=Mock(), canvas=canvas, scroll_remainder=0.0, queue_scroll=Mock())
        canvas.master = fake.root
        fake.route_scroll = lambda event, pixels: MusicMatchApp.route_scroll(fake, event, pixels)
        fake.root.winfo_containing.return_value = canvas
        event = SimpleNamespace(x_root=0, y_root=0, delta=1)
        for _ in range(5):
            MusicMatchApp.scroll_recommendations(fake, event)
        fake.queue_scroll.assert_called_once_with(-1)
        fake.queue_scroll.reset_mock()
        fake.scroll_remainder = 0.0
        event.delta = 120
        MusicMatchApp.scroll_recommendations(fake, event)
        fake.queue_scroll.assert_called_once_with(-36)
        fake.queue_scroll.reset_mock()
        # Tk 9 packs X in the upper16 bits and signed Y in the lower16.
        fake.scroll_remainder = 0.0
        event.delta = (12 << 16) | (-10 & 0xffff)
        MusicMatchApp.scroll_touchpad(fake, event)
        fake.queue_scroll.assert_called_once_with(8)
        fake.queue_scroll.reset_mock()
        event.delta = 12 << 16
        MusicMatchApp.scroll_touchpad(fake, event)
        fake.queue_scroll.assert_not_called()
        fake.root.winfo_containing.return_value = None
        self.assertIsNone(MusicMatchApp.scroll_recommendations(fake, event))

    def test_native_tk9_touchpad_scrolls_over_controls_and_animates(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = FeedbackStore(Path(temporary) / "scroll.sqlite3")
            root = tk.Tk()
            app = None
            try:
                with patch("data.main.MusicRecommender", return_value=DemoEngine()), patch("data.main.FeedbackStore", return_value=store):
                    app = MusicMatchApp(root)
                    self.wait(root, app)
                root.geometry("560x650")
                songs = [dict(DemoEngine.suggestion, track_id=f"scroll-{i}") for i in range(5)]
                app.show_recommendations(("scroll-test", songs), scroll=False)
                for _ in range(5):
                    root.update()
                try:
                    root.bind_class(app.wheel_tag, "<TouchpadScroll>")
                except tk.TclError:
                    self.skipTest("Tk 8.6 delivers touchpad input as MouseWheel")
                title = next(w for w in self.descendants(app.page) if isinstance(w, tk.ttk.Label) and w.cget("text") == "Find your next favorite.")
                for widget in (title, app.entry, app.search_button, app.profile_picker, app.page_scrollbar):
                    app.stop_scroll()
                    app.canvas.yview_moveto(0)
                    root.update()
                    start = app.canvas.canvasy(0)
                    value = app.profile_name.get()
                    # Synthetic delivery should not depend on another desktop window
                    # covering this test window. Outside routing is tested separately.
                    first_steps = []
                    animate = app.animate_scroll
                    def observe_animation():
                        before = app.canvas.canvasy(0)
                        animate()
                        first_steps.append(app.canvas.canvasy(0) - before)
                    # update() can process multiple 16 ms timers on a loaded desktop.
                    # Observe the actual first frame rather than elapsed wall time.
                    with patch.object(root, "winfo_containing", return_value=widget), patch.object(app, "animate_scroll", side_effect=observe_animation):
                        widget.event_generate("<TouchpadScroll>", delta=(-30 & 0xffff),
                                              rootx=widget.winfo_rootx() + 3, rooty=widget.winfo_rooty() + 3)
                        root.update()
                    self.assertTrue(first_steps, "Gesture must schedule an animation frame")
                    first = first_steps[0]
                    self.assertGreater(first, 0, str(widget))
                    self.assertLess(first, 24, "Gesture should be animated, not one jump")
                    deadline = time.monotonic() + 1
                    while app.scroll_job is not None and time.monotonic() < deadline:
                        root.update()
                        time.sleep(.01)
                    self.assertIsNone(app.scroll_job)
                    self.assertAlmostEqual(app.canvas.canvasy(0) - start, 24, delta=2)
                    self.assertEqual(app.profile_name.get(), value, "Scrolling must not change the active user")
            finally:
                if app:
                    app.close()
                else:
                    root.destroy()

    def test_result_added_state_filters_collapse_profiles_and_failed_save(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = FeedbackStore(Path(temporary) / "favorites.sqlite3")
            root = tk.Tk()
            root.withdraw()
            app = None
            try:
                with patch("data.main.MusicRecommender", return_value=DemoEngine()), patch("data.main.FeedbackStore", return_value=store):
                    app = MusicMatchApp(root)
                    self.wait(root, app)
                first, second = dict(DemoEngine.favorite), dict(DemoEngine.suggestion)
                app.show_matches([first, second])
                with patch.object(store, "save_favorites", side_effect=OSError("Synthetic save failure")), patch("data.main.messagebox.showerror"):
                    app.search_result_buttons["a"].invoke()
                    self.assertEqual(app.search_result_buttons["a"].cget("text"), "Add")
                    self.wait(root, app)
                self.assertNotIn("a", app.favorites)
                self.assertEqual(app.search_result_buttons["a"].cget("text"), "Add")
                app.search_result_buttons["a"].invoke()
                self.wait(root, app)
                self.assertEqual(app.search_result_buttons["a"].cget("text"), "Added")
                self.assertEqual(str(app.search_result_buttons["a"].cget("state")), "disabled")
                app.search_result_buttons["b"].invoke()
                self.wait(root, app)
                app.more_songs()
                app.show_matches([first, second])
                self.assertEqual(app.search_result_buttons["a"].cget("text"), "Added")
                app.favorite_query.set("Suggestion")
                root.update()
                radios = [widget for widget in self.descendants(app.favorite_rows) if isinstance(widget, tk.ttk.Radiobutton)]
                self.assertEqual([widget.cget("value") for widget in radios], ["b"])
                radios[0].invoke()
                app.remove_favorite()
                self.wait(root, app)
                self.assertEqual(list(app.favorites), ["a"])
                app.toggle_favorites()
                self.assertTrue(app.favorites_collapsed)
                self.assertFalse(app.favorites_content.winfo_manager())
                self.assertEqual([song["track_id"] for song in store.load_profile("personal")["favorites"]], ["a"])
                app.toggle_favorites()
                self.assertFalse(app.favorites_collapsed)
                app.profile_name.set("Test")
                app.switch_profile()
                self.wait(root, app)
                app.show_matches([first])
                self.assertEqual(app.search_result_buttons["a"].cget("text"), "Add")
                app.profile_name.set("Personal")
                app.switch_profile()
                self.wait(root, app)
                app.show_matches([first])
                self.assertEqual(app.search_result_buttons["a"].cget("text"), "Added")
                app.apply_profile(FeedbackStore(store.path).load_profile("personal"))
                app.show_matches([first])
                self.assertEqual(app.search_result_buttons["a"].cget("text"), "Added")
            finally:
                if app:
                    app.close()
                else:
                    root.destroy()

    def test_search_favorites_recommendations_and_changed_vote(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = FeedbackStore(Path(temporary) / "feedback.sqlite3")
            root = tk.Tk()
            root.withdraw()
            app = None
            try:
                with patch("data.main.MusicRecommender", return_value=DemoEngine()), patch("data.main.FeedbackStore", return_value=store):
                    app = MusicMatchApp(root)
                    self.wait(root, app)
                app.query.set("Favorite")
                app.search()
                self.wait(root, app)
                app.search_result_buttons["a"].invoke()
                self.wait(root, app)
                self.assertEqual(list(app.favorites), ["a"])
                app.recommend()
                self.wait(root, app)
                app.reflow_layout(600)
                self.assertEqual(app.layout_mode, "stacked")
                self.assertEqual(int(app.favorites_panel.grid_info()["row"]), 1)
                app.reflow_layout(1100)
                self.assertEqual(app.layout_mode, "columns")
                self.assertEqual(int(app.favorites_panel.grid_info()["column"]), 1)
                self.assertIs(app.page.master, app.canvas)
                view = app.recommendation_views[0]
                with patch.object(view["card"], "winfo_width", return_value=540):
                    app.wrap_labels()
                    self.assertLessEqual(int(view["detail"].cget("wraplength")), 540 - 44 - 8)
                self.assertFalse(view["detail"].winfo_manager())
                view["details_button"].invoke()
                root.update_idletasks()
                self.assertTrue(view["expanded"])
                self.assertEqual(view["detail"].winfo_manager(), "grid")
                view["details_button"].invoke()
                self.assertFalse(view["expanded"])
                self.assertFalse(view["detail"].winfo_manager())
                card = app.cards.winfo_children()[0]
                buttons = {widget.cget("text"): widget for widget in self.descendants(card) if isinstance(widget, tk.ttk.Button)}
                buttons["Yes"].invoke()
                self.wait(root, app)
                self.assertEqual(store.feedback_counts(), (1, 0))
                with patch.object(store, "feedback_counts", side_effect=OSError("Synthetic totals failure")):
                    buttons["No"].invoke()
                    self.wait(root, app)
                self.assertIn("Feedback saved", app.status.get())
                self.assertIn("could not refresh", app.status.get())
                self.assertEqual(store.feedback_counts(), (0, 1))
                self.assertEqual(view["buttons"][False].cget("style"), "Selected.TButton")
                self.assertEqual(view["buttons"][True].cget("style"), "TButton")
                reopened = FeedbackStore(store.path)
                app.apply_profile(reopened.load_profile("personal"))
                restored = app.recommendation_views[0]
                self.assertEqual(restored["response"].get(), "Saved: No")
                self.assertEqual(restored["buttons"][False].cget("style"), "Selected.TButton")
                app.selected_favorite.set("a")
                app.remove_favorite()
                self.wait(root, app)
                self.assertFalse(app.favorites)
                self.assertEqual(str(app.recommend_button.cget("state")), "disabled")
            finally:
                if app:
                    app.close()
                else:
                    root.destroy()

    def test_history_preserves_favorites_reason_changes_and_fresh_exhaustion(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = FeedbackStore(Path(temporary) / "history.sqlite3")
            old = store.save_batch([dict(DemoEngine.favorite)], [dict(DemoEngine.suggestion)])
            store.save_feedback(old, "b", False, reason="Wrong mood")
            current = dict(DemoEngine.favorite, track_id="c", track_name="Current favorite")
            store.save_favorites("personal", [current])
            root = tk.Tk()
            root.withdraw()
            app = None
            try:
                with patch("data.main.MusicRecommender", return_value=DemoEngine()), patch("data.main.FeedbackStore", return_value=store):
                    app = MusicMatchApp(root)
                    self.wait(root, app)
                app.history_filter.set("No")
                app.toggle_history()
                self.wait(root, app)
                self.assertEqual([row["batch_id"] for row in app.history_rows], [old])
                app.open_history()
                self.wait(root, app)
                self.assertEqual(list(app.favorites), ["c"])
                self.assertEqual(store.load_profile("personal")["favorites"][0]["track_id"], "c")
                view = app.recommendation_views[0]
                self.assertEqual(view["reason_var"].get(), "Wrong mood")
                with patch.object(store, "save_feedback", side_effect=OSError("Synthetic rating failure")), patch("data.main.messagebox.showerror"):
                    view["reason_var"].set("Too fast")
                    view["reason_picker"].event_generate("<<ComboboxSelected>>")
                    self.wait(root, app)
                self.assertEqual(view["reason_var"].get(), "Wrong mood")
                self.assertEqual(store.load_batch("personal", old)["recommendations"][0]["feedback_reason"], "Wrong mood")
                view["reason_var"].set("Too slow")
                view["reason_picker"].event_generate("<<ComboboxSelected>>")
                self.wait(root, app)
                self.assertEqual(store.load_batch("personal", old)["recommendations"][0]["feedback_reason"], "Too slow")
                view["buttons"][True].invoke()
                self.wait(root, app)
                self.assertIsNone(store.load_batch("personal", old)["recommendations"][0]["feedback_reason"])
                app.fresh_only.set(True)
                app.recommend()
                self.wait(root, app)
                self.assertEqual(app.recommendation_views, [])
                reopened = FeedbackStore(store.path)
                self.assertIsNone(reopened.load_profile("personal")["batch_id"])
                self.assertEqual(len(reopened.list_history("personal")), 1)
                app.apply_profile(reopened.load_profile("personal"))
                self.assertEqual(app.recommendation_views, [])
                self.assertEqual(list(app.favorites), ["c"])
            finally:
                if app:
                    app.close()
                else:
                    root.destroy()

    def test_metadata_only_fresh_exhaustion_clears_current_and_keeps_history(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            audio_path = directory / "audio.csv"
            audio_path.write_text(
                "track_id,track_name,artists,duration_ms,valence,tempo,energy,danceability\n"
                "b,Discovery,Artist B,180000,0.5,100,0.5,0.5\n", encoding="utf-8")
            seed = "00000000-0000-4000-8000-000000000001"
            candidate = "00000000-0000-4000-8000-000000000002"
            artist = "00000000-0000-4000-8000-000000000011"
            other_artist = "00000000-0000-4000-8000-000000000012"
            catalog_path = directory / "catalog.json"
            catalog_path.write_text(json.dumps({"schema_version": 1, "tracks": [
                {"mbid": seed, "title": "Catalog favorite", "artist_names": ["Artist A"],
                 "artist_mbids": [artist], "source": "musicbrainz", "license": "CC0-1.0"},
                {"mbid": candidate, "title": "Discovery", "artist_names": ["Artist B"],
                 "artist_mbids": [other_artist], "duration_ms": 180000,
                 "source": "musicbrainz", "license": "CC0-1.0"}],
                "related_edges": [{"seed_artist_mbid": artist, "recording_mbid": candidate,
                                   "source": "listenbrainz", "license": "CC0-1.0"}]}), encoding="utf-8")
            engine = HybridRecommender(audio_path, catalog_path)
            favorite = engine.get_song("mb:" + seed)
            self.assertNotIn("tempo", favorite)
            store = FeedbackStore(directory / "metadata.sqlite3")
            store.save_favorites("personal", [favorite])
            root = tk.Tk()
            root.withdraw()
            app = None
            try:
                with patch("data.main.MusicRecommender", return_value=engine), patch("data.main.FeedbackStore", return_value=store), patch("data.main.messagebox.showerror") as error:
                    app = MusicMatchApp(root)
                    self.wait(root, app)
                    app.recommend()
                    self.wait(root, app)
                    self.assertEqual(len(app.recommendation_views), 1)
                    original_batch = app.displayed_batch
                    app.fresh_only.set(True)
                    app.recommend()
                    self.wait(root, app)
                    error.assert_not_called()
                self.assertEqual(app.recommendation_views, [])
                self.assertIsNone(app.displayed_batch)
                reopened = FeedbackStore(store.path)
                self.assertIsNone(reopened.load_profile("personal")["batch_id"])
                self.assertEqual([row["batch_id"] for row in reopened.list_history("personal")], [original_batch])
                self.assertEqual(reopened.load_profile("personal")["favorites"], [favorite])
            finally:
                if app:
                    app.close()
                else:
                    root.destroy()

    def test_rich_neighborhood_cards_and_rating_preserve_vector_context(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            common = dict(valence=.5, energy=.5, danceability=.5, instrumentalness=.1,
                          loudness=-10, liveness=.1, duration_ms=200000, key=0, mode=1, time_signature=4)
            rows = [dict(common, track_id=identifier, track_name=identifier, artists=identifier,
                         tempo=tempo, acousticness=acoustic, speechiness=speech)
                    for identifier, tempo, acoustic, speech in [
                        ("slow", 65, .05, .8), ("fast", 180, .95, .05),
                        ("slow_match", 66, .06, .79), ("fast_match", 179, .94, .06),
                        ("middle", 115, .5, .4), ("far", 220, .01, .01)]]
            csv_path = directory / "rich.csv"
            pd.DataFrame(rows).to_csv(csv_path, index=False)
            engine = HybridRecommender(csv_path)
            self.assertTrue(engine.audio.vectors_active)
            store = FeedbackStore(directory / "rich.sqlite3")
            store.save_favorites("personal", [engine.get_song("slow"), engine.get_song("fast")])
            root = tk.Tk()
            root.withdraw()
            app = None
            try:
                with patch("data.main.MusicRecommender", return_value=engine), patch("data.main.FeedbackStore", return_value=store), patch("data.main.messagebox.showerror") as error:
                    app = MusicMatchApp(root)
                    self.wait(root, app)
                    app.recommend()
                    self.wait(root, app)
                    self.assertTrue(app.recommendation_views)
                    first = app.recommendation_views[0]
                    self.assertIn(first["song"]["neighborhood_context"]["anchor_id"], ("slow", "fast"))
                    self.assertIn("Close to", app.reason_preview(first["song"]))
                    first["buttons"][True].invoke()
                    self.wait(root, app)
                    error.assert_not_called()
                    saved = store.training_feedback()[0]
                    self.assertTrue(saved["liked"])
                    self.assertEqual(saved["feature_version"], first["song"]["feature_version"])
                    self.assertEqual(saved["neighborhood_context"], first["song"]["neighborhood_context"])
            finally:
                if app:
                    app.close()
                else:
                    root.destroy()

    def wait(self, root, app):
        deadline = time.monotonic() + 10
        while app.busy and time.monotonic() < deadline:
            root.update()
            time.sleep(.01)
        root.update()
        self.assertFalse(app.busy, "Background action did not complete")


if __name__ == "__main__":
    unittest.main()
