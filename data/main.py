"""MusicMatch: one gently scrolling desktop page with profile-scoped feedback."""
from concurrent.futures import ThreadPoolExecutor
from queue import Empty, Queue
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import re
import tkinter as tk
from tkinter import messagebox, ttk

if __package__:
    from .backend import FEEDBACK_REASONS, FeedbackStore
    from .hybrid import MusicRecommender
else:
    from backend import FEEDBACK_REASONS, FeedbackStore
    from hybrid import MusicRecommender

NAVY = "#002E5D"
ROYAL = "#003DA5"
WHITE = "#FFFFFF"
BACKGROUND = "#F2F5F9"
INK = "#162C43"
MUTED = "#52667A"
BORDER = "#DCE4ED"


class MusicMatchApp:
    def __init__(self, root):
        self.root = root
        self.engine = None
        self.store = None
        self.favorites = {}
        self.profile_id = "personal"
        self.profiles = []
        self.scroll_remainder = 0.0
        self.scroll_target = None
        self.scroll_job = None
        self._scroll_region = None
        self._page_width = None
        self.matches = {}
        self.search_result_buttons = {}
        self.favorites_collapsed = False
        self.recommendation_views = []
        self.history_mode = False
        self.displayed_batch = None
        self.displayed_rating = "all"
        self.history_rows = []
        self.history_offset = 0
        self.history_has_older = False
        self.closed = False
        self.busy = False
        self.events = Queue()
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.layout_mode = None
        root.title("MusicMatch")
        root.geometry("1120x850")
        root.minsize(540, 480)
        root.configure(bg=BACKGROUND)
        self.configure_styles()

        # The only canvas/scrollbar surrounds the entire document.
        self.viewport = ttk.Frame(root)
        self.viewport.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(self.viewport, bg=BACKGROUND, highlightthickness=0, yscrollincrement=1)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.page_scrollbar = ttk.Scrollbar(self.viewport, orient="vertical", command=self.canvas.yview)
        self.page_scrollbar.pack(side="right", fill="y")
        self.canvas.configure(yscrollcommand=self.page_scrollbar.set)
        self.page = ttk.Frame(self.canvas)
        self.page_window = self.canvas.create_window((0, 0), window=self.page, anchor="nw")
        self.page.bind("<Configure>", self.update_scroll_region)
        self.canvas.bind("<Configure>", self.resize_page)

        header = ttk.Frame(self.page, style="Hero.TFrame", padding=(28, 24))
        header.pack(fill="x")
        ttk.Label(header, text="MUSIC / MATCH", style="Eyebrow.TLabel").pack(anchor="w")
        ttk.Label(header, text="Find your next favorite.", style="Hero.TLabel").pack(anchor="w", pady=(8, 6))
        ttk.Label(header, text="Start with songs you love. Shape the next suggestions with your feedback.", style="HeroSub.TLabel", wraplength=950).pack(anchor="w")

        self.body = ttk.Frame(self.page, padding=(28, 20))
        self.body.pack(fill="x")
        profile_row = ttk.Frame(self.body)
        profile_row.pack(fill="x", pady=(0, 16))
        ttk.Label(profile_row, text="Listening as", style="Muted.TLabel").pack(side="left", padx=(0, 10))
        self.profile_name = tk.StringVar(value="Personal")
        self.profile_picker = ttk.Combobox(profile_row, textvariable=self.profile_name, values=("Personal", "Test"), state="disabled", width=12)
        self.profile_picker.pack(side="left")
        self.profile_picker.bind("<<ComboboxSelected>>", self.switch_profile)
        self.reset_button = ttk.Button(profile_row, text="Reset Test user", command=self.reset_test, style="Small.TButton")

        self.upper = ttk.Frame(self.body)
        self.upper.pack(fill="x")
        self.search_panel = ttk.Frame(self.upper, style="Card.TFrame", padding=20)
        self.favorites_panel = ttk.Frame(self.upper, style="Card.TFrame", padding=20)
        self.search_panel.grid(row=0, column=0, sticky="new", padx=(0, 10))
        self.favorites_panel.grid(row=0, column=1, sticky="new", padx=(10, 0))
        self.upper.columnconfigure(0, weight=3, uniform="panels")
        self.upper.columnconfigure(1, weight=2, uniform="panels")
        ttk.Label(self.search_panel, text="01 / FIND YOUR SONGS", style="Kicker.TLabel").pack(anchor="w")
        ttk.Label(self.search_panel, text="What have you been listening to?", style="CardHeading.TLabel", wraplength=500).pack(anchor="w", pady=(8, 12))
        search_row = ttk.Frame(self.search_panel, style="Card.TFrame")
        search_row.pack(fill="x")
        self.query = tk.StringVar()
        ttk.Label(search_row, text="Song title", style="CardMuted.TLabel").pack(anchor="w", pady=(0, 3))
        self.entry = ttk.Entry(search_row, textvariable=self.query, font=("Segoe UI", 11), width=12)
        self.entry.pack(fill="x", ipady=6)
        self.entry.bind("<Return>", lambda event: self.search())
        self.artist_query = tk.StringVar()
        ttk.Label(search_row, text="Artist (optional)", style="CardMuted.TLabel").pack(anchor="w", pady=(10, 3))
        self.artist_entry = ttk.Entry(search_row, textvariable=self.artist_query, font=("Segoe UI", 11), width=12)
        self.artist_entry.pack(fill="x", ipady=6)
        self.artist_entry.bind("<Return>", lambda event: self.search())
        self.search_button = ttk.Button(search_row, text="Search", command=self.search)
        self.search_button.pack(anchor="w", pady=(10, 0))
        ttk.Label(self.search_panel, text="Use either field, or both to narrow your search.", style="CardMuted.TLabel").pack(anchor="w", pady=(6, 12))
        self.results = ttk.Frame(self.search_panel, style="Card.TFrame")
        self.results.pack(fill="x")
        self.selected_match = tk.StringVar()
        ttk.Label(self.favorites_panel, text="02 / YOUR STARTING POINT", style="Kicker.TLabel").pack(anchor="w")
        self.favorite_title = tk.StringVar(value="Your favorites (0)")
        ttk.Label(self.favorites_panel, textvariable=self.favorite_title, style="CardHeading.TLabel").pack(anchor="w", pady=(8, 12))
        self.favorites_toggle = ttk.Button(self.favorites_panel, text="Hide favorites", command=self.toggle_favorites, style="Small.TButton")
        self.favorites_toggle.pack(anchor="w", pady=(0, 10))
        self.favorites_content = ttk.Frame(self.favorites_panel, style="Card.TFrame")
        self.favorites_content.pack(fill="x")
        self.favorite_query = tk.StringVar()
        ttk.Label(self.favorites_content, text="Find a saved song or artist", style="CardMuted.TLabel").pack(anchor="w", pady=(0, 3))
        self.favorite_filter_entry = ttk.Entry(self.favorites_content, textvariable=self.favorite_query, width=12)
        self.favorite_filter_entry.pack(fill="x", ipady=4, pady=(0, 10))
        self.favorite_filter_status = tk.StringVar()
        ttk.Label(self.favorites_content, textvariable=self.favorite_filter_status, style="CardMuted.TLabel").pack(anchor="w")
        self.favorite_query.trace_add("write", lambda *args: self.render_favorites())
        self.favorite_rows = ttk.Frame(self.favorites_content, style="Card.TFrame")
        self.favorite_rows.pack(fill="x")
        self.selected_favorite = tk.StringVar()
        self.remove_button = ttk.Button(self.favorites_content, text="Remove selected", command=self.remove_favorite, style="Small.TButton")
        self.remove_button.pack(anchor="w", pady=(12, 0))

        actions = ttk.Frame(self.body)
        actions.pack(fill="x", pady=(18, 10))
        self.recommend_button = ttk.Button(actions, text="Suggest songs", style="Accent.TButton", command=self.recommend)
        self.recommend_button.pack(side="left")
        self.more_button = ttk.Button(actions, text="Add more songs", command=self.more_songs)
        self.more_button.pack(side="left", padx=8)
        self.retry_button = ttk.Button(actions, text="Retry loading", command=lambda: self.submit(self.load, self.loaded))
        self.fresh_only = tk.BooleanVar(value=False)
        self.fresh_check = ttk.Checkbutton(self.body, text="Fresh suggestions (skip songs already shown)", variable=self.fresh_only)
        self.fresh_check.pack(anchor="w", pady=(0, 5))
        ttk.Label(self.body, text="Songs you marked No are excluded from new suggestions. You can revisit them in history.", style="Muted.TLabel", wraplength=980).pack(anchor="w", pady=(0, 10))
        self.status = tk.StringVar(value="Loading your song library...")
        ttk.Label(self.body, textvariable=self.status, style="Muted.TLabel", wraplength=980).pack(anchor="w", pady=(0, 22))
        ttk.Separator(self.body).pack(fill="x", pady=(0, 22))
        ttk.Label(self.body, text="03 / MADE FROM YOUR FAVORITES", style="PageKicker.TLabel").pack(anchor="w")
        self.recommendation_heading = ttk.Label(self.body, text="Your next discoveries", style="Heading.TLabel")
        self.recommendation_heading.pack(anchor="w", pady=(7, 6))
        ttk.Label(self.body, text="Does it feel like a good match? Your Yes or No shapes future suggestions.", style="Muted.TLabel", wraplength=980).pack(anchor="w", pady=(0, 16))
        self.history_toggle = ttk.Button(self.body, text="Browse recommendation history", command=self.toggle_history, style="Small.TButton")
        self.history_toggle.pack(anchor="w", pady=(0, 10))
        self.history_panel = ttk.Frame(self.body, style="Card.TFrame", padding=16)
        self.history_filter = tk.StringVar(value="All")
        ttk.Label(self.history_panel, text="Filter saved sessions", style="CardMuted.TLabel").pack(anchor="w")
        self.history_filter_picker = ttk.Combobox(self.history_panel, textvariable=self.history_filter, values=("All", "Yes", "No", "Unrated"), state="readonly", width=12)
        self.history_filter_picker.pack(anchor="w", pady=(4, 10))
        self.history_filter_picker.bind("<<ComboboxSelected>>", lambda event: self.refresh_history())
        self.history_selection = tk.StringVar()
        self.history_picker = ttk.Combobox(self.history_panel, textvariable=self.history_selection, state="readonly", width=12)
        self.history_picker.pack(fill="x", pady=(0, 10))
        history_actions = ttk.Frame(self.history_panel, style="Card.TFrame")
        history_actions.pack(fill="x")
        self.history_open = ttk.Button(history_actions, text="Open session", command=self.open_history, style="Small.TButton")
        self.history_open.pack(side="left")
        self.history_newer = ttk.Button(history_actions, text="Newer", command=lambda: self.page_history(-1), style="Small.TButton")
        self.history_newer.pack(side="left", padx=8)
        self.history_older = ttk.Button(history_actions, text="Older", command=lambda: self.page_history(1), style="Small.TButton")
        self.history_older.pack(side="left")
        self.history_note = tk.StringVar(value="History is saved separately for each user.")
        ttk.Label(self.history_panel, textvariable=self.history_note, style="CardMuted.TLabel", wraplength=800).pack(anchor="w", pady=(10, 0))
        self.view_context = tk.StringVar(value="Current suggestions")
        self.view_context_label = ttk.Label(self.body, textvariable=self.view_context, style="Muted.TLabel", wraplength=980)
        self.view_context_label.pack(anchor="w", pady=(0, 10))
        self.back_current = ttk.Button(self.body, text="Back to current suggestions", command=self.return_to_current, style="Small.TButton")
        self.cards = ttk.Frame(self.body)
        self.cards.pack(fill="x")
        self.context_status = tk.StringVar(value="Favorites and feedback are saved separately for each user.")
        ttk.Label(self.body, textvariable=self.context_status, style="Muted.TLabel", wraplength=980).pack(anchor="w", pady=(14, 10))

        self.wheel_tag = f"MusicMatchWheel{id(self)}"
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            root.bind_class(self.wheel_tag, sequence, self.scroll_recommendations)
        # Tk 9 delivers two-finger gestures separately from mouse-wheel events.
        try:
            root.bind_class(self.wheel_tag, "<TouchpadScroll>", self.scroll_touchpad)
        except tk.TclError:
            pass  # Tk 8.6 uses MouseWheel for these gestures instead.
        root.bind("<FocusIn>", self.reveal_focus, add="+")
        root.bind("<ButtonPress-1>", lambda event: self.stop_scroll(), add="+")
        self.show_matches([], searched=False)
        self.render_favorites()
        self.clear_cards()
        self.install_wheel_binding(root)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(80, self.poll)
        self.submit(self.load, self.loaded)

    def configure_styles(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background=BACKGROUND)
        style.configure("Card.TFrame", background=WHITE)
        style.configure("Hero.TFrame", background=NAVY)
        style.configure("TLabel", background=BACKGROUND, foreground=INK, font=("Segoe UI", 10))
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("Card.TLabel", background=WHITE)
        style.configure("CardMuted.TLabel", background=WHITE, foreground=MUTED)
        style.configure("Song.TLabel", background=WHITE, font=("Segoe UI", 11, "bold"))
        style.configure("CardHeading.TLabel", background=WHITE, font=("Segoe UI", 16, "bold"))
        style.configure("Heading.TLabel", font=("Segoe UI", 21, "bold"))
        style.configure("Kicker.TLabel", background=WHITE, foreground=ROYAL, font=("Segoe UI", 9, "bold"))
        style.configure("PageKicker.TLabel", foreground=ROYAL, font=("Segoe UI", 9, "bold"))
        style.configure("Hero.TLabel", background=NAVY, foreground=WHITE, font=("Segoe UI", 29, "bold"))
        style.configure("HeroSub.TLabel", background=NAVY, foreground="#DFE9F5", font=("Segoe UI", 11))
        style.configure("Eyebrow.TLabel", background=NAVY, foreground="#B5CEEC", font=("Segoe UI", 9, "bold"))
        style.configure("TButton", background=WHITE, foreground=NAVY, bordercolor=BORDER, font=("Segoe UI", 10), padding=(12, 9))
        style.map("TButton", background=[("active", "#E9EFF8"), ("disabled", "#E8EDF3")], foreground=[("disabled", "#64788E")])
        style.configure("Small.TButton", padding=(9, 6))
        style.configure("Added.TButton", background="#E7EFFA", foreground=ROYAL, bordercolor=BORDER, padding=(9, 6))
        style.map("Added.TButton", background=[("disabled", "#E7EFFA")], foreground=[("disabled", ROYAL)])
        for name in ("Accent.TButton", "Selected.TButton"):
            style.configure(name, background=ROYAL, foreground=WHITE, bordercolor=ROYAL)
            style.map(name, background=[("disabled", "#A6B8D2"), ("active", NAVY)], foreground=[("disabled", WHITE), ("active", WHITE)])
        style.configure("Card.TRadiobutton", background=WHITE)
        style.configure("TCheckbutton", background=BACKGROUND, foreground=INK, font=("Segoe UI", 10))
        style.map("Card.TRadiobutton", background=[("active", WHITE)])
        style.configure("TEntry", padding=4)

    def update_scroll_region(self, event=None):
        bounds = self.canvas.bbox("all")
        if bounds != self._scroll_region:
            self._scroll_region = bounds
            self.canvas.configure(scrollregion=bounds)

    def resize_page(self, event):
        width = event.width
        if width == self._page_width:
            return
        self._page_width = width
        self.stop_scroll()
        self.canvas.itemconfigure(self.page_window, width=width)
        self.reflow_layout(width)
        self.root.after_idle(self.wrap_labels)

    def reflow_layout(self, width):
        mode = "stacked" if width < 860 else "columns"
        if mode == self.layout_mode:
            return
        self.layout_mode = mode
        self.search_panel.grid_configure(row=0, column=0, padx=(0, 0) if mode == "stacked" else (0, 10), pady=0, columnspan=1)
        if mode == "stacked":
            self.favorites_panel.grid_configure(row=1, column=0, padx=0, pady=(16, 0))
            self.upper.columnconfigure(0, weight=1, uniform="")
            self.upper.columnconfigure(1, weight=0, uniform="")
        else:
            self.favorites_panel.grid_configure(row=0, column=1, padx=(10, 0), pady=0)
            self.upper.columnconfigure(0, weight=3, uniform="panels")
            self.upper.columnconfigure(1, weight=2, uniform="panels")

    def wrap_labels(self):
        if self.closed:
            return
        def visit(widget):
            for child in widget.winfo_children():
                if isinstance(child, ttk.Label):
                    # Song text shares its row with a radio indicator. All other
                    # labels follow the actual width of their parent container.
                    parent = child.master
                    padding = parent.tk.splitlist(parent.cget("padding")) if "padding" in parent.keys() else ()
                    values = [parent.winfo_pixels(str(value)) for value in padding]
                    horizontal = (2 * values[0] if len(values) == 1 else values[0] + values[2] if len(values) >= 3 else 2 * values[0] if values else 0)
                    width = parent.winfo_width() - horizontal - 8
                    target = max(160, width)
                    if int(child.cget("wraplength") or 0) != target:
                        child.configure(wraplength=target)
                visit(child)
        visit(self.page)
        self.update_scroll_region()

    def scroll_recommendations(self, event):
        delta = getattr(event, "delta", 0)
        if getattr(event, "num", None) in (4, 5):
            delta = 120 if event.num == 4 else -120
        return self.route_scroll(event, -delta / 120 * 36)

    def scroll_touchpad(self, event):
        # Packed signed 16-bit X/Y deltas: ignore horizontal finger jitter.
        vertical = int(event.delta) & 0xffff
        if vertical >= 0x8000:
            vertical -= 0x10000
        return self.route_scroll(event, -vertical * 0.8)

    def route_scroll(self, event, pixels):
        widget = self.root.winfo_containing(event.x_root, event.y_root)
        while widget is not None:
            if widget is self.root:
                self.scroll_remainder += max(-120, min(120, pixels))
                pixels = int(self.scroll_remainder)
                self.scroll_remainder -= pixels
                if pixels:
                    self.queue_scroll(pixels)
                return "break"
            widget = getattr(widget, "master", None)

    def queue_scroll(self, pixels):
        bounds = self.canvas.bbox("all")
        if self.closed or not bounds:
            return
        current = self.canvas.canvasy(0) - bounds[1]
        maximum = max(0, bounds[3] - bounds[1] - self.canvas.winfo_height())
        target = self.scroll_target if self.scroll_target is not None else current
        if (target - current) * pixels < 0:
            target = current  # A reversal should immediately change direction.
        self.scroll_target = max(0, min(maximum, current + max(-240, min(240, target + pixels - current))))
        if self.scroll_job is None:
            self.scroll_job = self.root.after(0, self.animate_scroll)

    def animate_scroll(self):
        self.scroll_job = None
        if self.closed or self.scroll_target is None:
            return
        bounds = self.canvas.bbox("all")
        if not bounds:
            self.scroll_target = None
            return
        height = max(1, bounds[3] - bounds[1])
        maximum = max(0, height - self.canvas.winfo_height())
        target = max(0, min(maximum, self.scroll_target))
        current = self.canvas.canvasy(0) - bounds[1]
        remaining = target - current
        if abs(remaining) <= 1:
            self.canvas.yview_moveto(target / height)
            self.scroll_target = None
            return
        step = max(1, abs(remaining) * 0.4) * (1 if remaining > 0 else -1)
        self.canvas.yview_moveto((current + step) / height)
        self.scroll_job = self.root.after(16, self.animate_scroll)

    def stop_scroll(self):
        if self.scroll_job is not None:
            self.root.after_cancel(self.scroll_job)
            self.scroll_job = None
        self.scroll_target = None
        self.scroll_remainder = 0.0

    def install_wheel_binding(self, widget):
        tags = widget.bindtags()
        if self.wheel_tag not in tags:
            widget.bindtags((self.wheel_tag,) + tags)
        for child in widget.winfo_children():
            self.install_wheel_binding(child)

    def reveal_focus(self, event):
        if self.closed or event.widget is self.root:
            return
        widget = event.widget
        ancestor = widget
        while ancestor is not None and ancestor is not self.page:
            ancestor = getattr(ancestor, "master", None)
        if ancestor is None or self.canvas.winfo_height() < 10:
            return
        self.root.after_idle(lambda: self.reveal_widget(widget))

    def reveal_widget(self, widget):
        if self.closed or not widget.winfo_exists():
            return
        top = widget.winfo_rooty() - self.canvas.winfo_rooty()
        bottom = top + widget.winfo_height()
        if top < 8:
            self.stop_scroll()
            self.canvas.yview_scroll(int(top - 12), "units")
        elif bottom > self.canvas.winfo_height() - 8:
            self.stop_scroll()
            self.canvas.yview_scroll(int(bottom - self.canvas.winfo_height() + 12), "units")

    def scroll_to_widget(self, widget):
        if self.closed or not widget.winfo_exists():
            return
        bounds = self.canvas.bbox("all")
        if bounds:
            self.stop_scroll()
            y = self.canvas.canvasy(0) + widget.winfo_rooty() - self.canvas.winfo_rooty()
            self.canvas.yview_moveto(max(0, (y - 20) / max(1, bounds[3] - bounds[1])))

    def song_choice(self, parent, song, variable, value):
        row = ttk.Frame(parent, style="Card.TFrame", padding=(0, 8))
        row.pack(fill="x")
        radio = ttk.Radiobutton(row, variable=variable, value=value, style="Card.TRadiobutton")
        radio.pack(side="left", anchor="n", padx=(0, 6), pady=(3, 0))
        text = ttk.Frame(row, style="Card.TFrame")
        text.pack(side="left", fill="x", expand=True)
        for content, style in ((song.get("display_title", song["track_name"]), "Song.TLabel"), (song["artists"], "CardMuted.TLabel")):
            label = ttk.Label(text, text=content, style=style, wraplength=250)
            label.pack(anchor="w", fill="x")
            label.bind("<Button-1>", lambda event, v=value: variable.set(v))
            label.bind("<Double-1>", lambda event: self.add_favorite() if variable is self.selected_match else None)
        return row

    def search_result(self, song):
        row = ttk.Frame(self.results, style="Card.TFrame", padding=(0, 10))
        row.pack(fill="x")
        # Reserve action space before the text so long metadata wraps naturally.
        button = ttk.Button(row, text="Add", style="Small.TButton", command=lambda s=song: self.add_favorite(s))
        button.pack(side="right", anchor="n", padx=(10, 0))
        self.search_result_buttons[song["track_id"]] = button
        text = ttk.Frame(row, style="Card.TFrame")
        text.pack(side="left", fill="x", expand=True)
        for content, style in ((song.get("display_title", song["track_name"]), "Song.TLabel"), (song["artists"], "CardMuted.TLabel")):
            ttk.Label(text, text=content, style=style, wraplength=220).pack(anchor="w", fill="x")

    def update_add_buttons(self):
        for track_id, button in self.search_result_buttons.items():
            added = track_id in self.favorites
            button.configure(text="Added" if added else "Add", style="Added.TButton" if added else "Small.TButton",
                             state="disabled" if added or self.busy or self.engine is None else "normal")

    def toggle_favorites(self):
        self.favorites_collapsed = not self.favorites_collapsed
        if self.favorites_collapsed:
            self.favorites_content.pack_forget()
        else:
            self.favorites_content.pack(fill="x")
        self.favorites_toggle.configure(text="Show favorites" if self.favorites_collapsed else "Hide favorites")
        self.root.after_idle(self.wrap_labels)

    @staticmethod
    def history_date(value):
        try:
            moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
            return moment.astimezone(ZoneInfo("America/Denver")).strftime("%b %d, %Y, %I:%M %p %Z")
        except (TypeError, ValueError, AttributeError):
            return "Saved session"

    def toggle_history(self):
        if self.busy:
            return
        if self.history_panel.winfo_manager():
            self.history_panel.pack_forget()
            self.history_toggle.configure(text="Browse recommendation history")
        else:
            self.history_panel.pack(fill="x", pady=(0, 12), before=self.view_context_label)
            self.history_toggle.configure(text="Hide history browser")
            self.refresh_history()
        self.root.after_idle(self.wrap_labels)

    def refresh_history(self, offset=0):
        if self.busy or self.store is None:
            return
        profile, rating = self.profile_id, self.history_filter.get().lower()
        def done(rows):
            self.history_offset = offset
            self.set_history_rows(rows)
            self.status.set("Choose a saved session and click Open session. Current favorites stay unchanged.")
        self.submit(lambda: self.store.list_history(profile, rating=rating, limit=31, offset=offset), done)

    def set_history_rows(self, rows, selected_batch=None):
        self.history_has_older = len(rows) > 30
        self.history_rows = rows[:30]
        labels = [f"{self.history_date(row['created_at'])} | {row['recommendation_count']} total songs | {row['batch_id'][:6]}" for row in self.history_rows]
        self.history_picker.configure(values=labels)
        if labels:
            selected = next((i for i, row in enumerate(self.history_rows) if row["batch_id"] == selected_batch), 0)
            self.history_picker.current(selected)
        else:
            self.history_selection.set("")
        self.history_note.set(f"Showing sessions {self.history_offset + 1}–{self.history_offset + len(labels)} for {self.profile_name.get()}. Counts are totals before the rating filter." if labels else "No sessions on this page. Try Newer or another rating filter.")
        self.set_controls()
        self.root.after_idle(self.wrap_labels)

    def page_history(self, direction):
        if not self.busy:
            self.refresh_history(max(0, self.history_offset + direction * 30))

    def open_history(self):
        if self.busy:
            return
        index = self.history_picker.current()
        if not 0 <= index < len(self.history_rows):
            return
        profile = self.profile_id
        batch = self.history_rows[index]["batch_id"]
        rating = self.history_filter.get().lower()
        self.submit(lambda: self.store.load_batch(profile, batch, rating=rating), self.show_history_batch)

    def show_history_batch(self, data, scroll=True, rating=None):
        self.show_recommendations((data["batch_id"], data["recommendations"]), scroll=scroll, history=True,
                                  empty_text="No songs in this saved session match the selected rating filter.")
        self.displayed_rating = rating or self.history_filter.get().lower()
        self.view_context.set(f"History: {self.history_date(data['created_at'])}. Showing {self.displayed_rating} ratings, based on {len(data['favorites'])} favorites at the time. Your current favorites stay unchanged.")
        self.status.set("Viewing a saved session. You can update its votes or return to current suggestions.")

    def return_to_current(self):
        if self.busy:
            return
        def done(state):
            if state["batch_id"]:
                self.show_recommendations((state["batch_id"], state["recommendations"]))
            else:
                self.clear_cards()
                self.status.set("No current suggestions. Request a new batch using your saved favorites.")
        self.submit(lambda: self.store.load_profile(self.profile_id), done)

    @staticmethod
    def reason_preview(song):
        if song.get("reason_preview"):
            return song["reason_preview"]
        reason = song.get("reason", "")
        comparisons = reason.partition("favorites' average are ")[2].split(". Lower audio")[0]
        names = re.findall(r"(mood \(valence\)|tempo|energy|danceability) [\d.]+", comparisons)
        if names:
            labels = ["mood" if name.startswith("mood") else name for name in names]
            summary = "Closest audio traits to your favorites: " + " and ".join(labels) + "."
        else:
            summary = reason.split(". ")[0].rstrip(".") + "." if reason else "Selected using your favorites' audio features."
        if abs(song.get("feedback_adjustment", 0)) > 1e-9:
            summary += " Your saved ratings also helped shape this match."
        return summary
    def load(self):
        engine, store = MusicRecommender(), FeedbackStore()
        profile = store.get_active_profile()
        return engine, store, store.list_profiles(), profile, store.load_profile(profile)

    def loaded(self, result):
        self.engine, self.store, self.profiles, self.profile_id, state = result
        self.retry_button.pack_forget()
        self.apply_profile(state)
        audio = getattr(self.engine, "audio", None)
        if audio is not None and getattr(audio, "vector_warning", None):
            self.status.set("Using the original audio model. Rebuild the local song vectors to enable preference neighborhoods.")
        self.entry.focus_set()

    def update_counts(self, counts):
        self.context_status.set(f"{self.profile_name.get()}: {counts[0]} yes / {counts[1]} no saved. Your ratings gently personalize the next suggestions.")

    def apply_profile(self, state):
        self.profile_name.set(next(p["name"] for p in self.profiles if p["id"] == self.profile_id))
        self.favorites = {s["track_id"]: s for s in state["favorites"]}
        self.query.set("")
        self.artist_query.set("")
        self.favorite_query.set("")
        self.selected_favorite.set("")
        self.fresh_only.set(False)
        self.history_filter.set("All")
        self.history_offset = 0
        self.history_rows = []
        self.history_has_older = False
        self.history_selection.set("")
        self.history_picker.configure(values=())
        self.history_note.set("History is saved separately for each user.")
        self.history_panel.pack_forget()
        self.history_toggle.configure(text="Browse recommendation history")
        self.show_matches([], searched=False)
        self.refresh_favorites()
        if state["batch_id"] and state["recommendations"]:
            self.show_recommendations((state["batch_id"], state["recommendations"]), scroll=False)
        self.canvas.yview_moveto(0)
        self.update_counts(state["counts"])
        self.reset_button.pack_forget()
        if self.profile_id == "test":
            self.reset_button.pack(side="left", padx=12)
        self.status.set("Saved favorites and latest suggestions restored. Add songs or request new suggestions.")

    def switch_profile(self, event=None):
        if self.busy or self.store is None:
            return
        target = next(p["id"] for p in self.profiles if p["name"] == self.profile_name.get())
        self.profile_name.set(next(p["name"] for p in self.profiles if p["id"] == self.profile_id))
        def work():
            state = self.store.load_profile(target)
            self.store.set_active_profile(target)
            return state
        def done(state):
            self.profile_id = target
            self.apply_profile(state)
        self.submit(work, done)

    def reset_test(self):
        if self.busy or self.profile_id != "test":
            return
        if not messagebox.askyesno("Reset Test user", "Clear all Test favorites, suggestions and ratings? Personal data will stay saved.", parent=self.root):
            return
        def work():
            self.store.reset_profile("test")
            return self.store.load_profile("test")
        self.submit(work, self.apply_profile)

    def submit(self, work, done, on_error=None):
        if self.busy or self.closed:
            return
        self.busy = True
        self.set_controls()
        future = self.executor.submit(work)
        def complete(result):
            try:
                self.events.put((done, result.result(), None, on_error))
            except Exception as error:
                self.events.put((done, None, error, on_error))
        future.add_done_callback(complete)

    def poll(self):
        if self.closed:
            return
        try:
            while True:
                done, result, error, on_error = self.events.get_nowait()
                self.busy = False
                if error:
                    if on_error:
                        on_error()
                    self.status.set("Could not complete that action. Please try again." if self.engine else "Library loading failed. Fix the error, then click Retry loading.")
                    if self.engine is None:
                        self.retry_button.pack(side="left", padx=8)
                    messagebox.showerror("MusicMatch", str(error), parent=self.root)
                else:
                    done(result)
                self.set_controls()
        except Empty:
            pass
        self.root.after(80, self.poll)

    def set_controls(self):
        state = "normal" if self.engine is not None and not self.busy else "disabled"
        for widget in (self.search_button, self.remove_button, self.more_button, self.entry, self.artist_entry, self.favorite_filter_entry):
            widget.configure(state=state)
        self.favorites_toggle.configure(state=state)
        for widget in (self.fresh_check, self.history_toggle, self.back_current):
            widget.configure(state=state)
        self.history_filter_picker.configure(state="readonly" if state == "normal" else "disabled")
        self.history_picker.configure(state="readonly" if state == "normal" and self.history_rows else "disabled")
        self.history_open.configure(state=state if self.history_rows else "disabled")
        self.history_newer.configure(state=state if self.history_offset else "disabled")
        self.history_older.configure(state=state if self.history_has_older else "disabled")
        self.update_add_buttons()
        self.recommend_button.configure(state=state if self.favorites else "disabled")
        self.retry_button.configure(state="disabled" if self.busy else "normal")
        self.profile_picker.configure(state="readonly" if self.engine is not None and not self.busy else "disabled")
        self.reset_button.configure(state="normal" if self.profile_id == "test" and not self.busy else "disabled")
        for view in self.recommendation_views:
            for button in view["buttons"].values():
                button.configure(state=state)
            view["reason_picker"].configure(state="readonly" if state == "normal" and view["song"].get("liked") is False else "disabled")

    def search(self):
        if self.busy or self.engine is None:
            return
        query = self.query.get().strip()
        artist = self.artist_query.get().strip()
        if not query and not artist:
            self.status.set("Enter a song title, an artist, or both.")
            return
        self.status.set("Searching...")
        self.submit(lambda: self.engine.search(query, artist_query=artist, title_only=True), self.show_matches)

    def show_matches(self, songs, searched=True):
        for child in self.results.winfo_children():
            child.destroy()
        self.selected_match.set("")
        self.search_result_buttons = {}
        self.matches = {str(i): song for i, song in enumerate(songs)}
        for key, song in self.matches.items():
            self.search_result(song)
        if not songs:
            text = "No matches. Try fewer words or clear the artist filter." if searched else "Search above to find a song you love."
            ttk.Label(self.results, text=text, style="CardMuted.TLabel", wraplength=250).pack(anchor="w", pady=8)
        self.update_add_buttons()
        self.install_wheel_binding(self.results)
        self.root.after_idle(self.wrap_labels)
        if self.engine is not None and searched:
            self.status.set(f"Showing {len(songs)} matches. Click Add beside a song." if songs else "No matches found. Try another title, artist, or spelling.")

    def add_favorite(self, song=None):
        if self.busy:
            return
        if song is None:
            selection = self.selected_match.get()
            if selection not in self.matches:
                self.status.set("Click Add beside a song in the search results.")
                return
            song = self.matches[selection]
        if song["track_id"] in self.favorites:
            self.status.set("That song is already in your favorites.")
            return
        favorites = list(self.favorites.values()) + [song]
        self.persist_favorites(favorites)

    def persist_favorites(self, favorites):
        profile = self.profile_id
        self.status.set("Saving your favorites...")
        def work():
            self.store.save_favorites(profile, favorites)
        def saved(_):
            self.favorites = {s["track_id"]: s for s in favorites}
            self.refresh_favorites()
            self.status.set("Favorites saved. Add another song or click Suggest songs.")
        self.submit(work, saved)

    def remove_favorite(self):
        if self.busy:
            return
        selection = self.selected_favorite.get()
        if selection in self.favorites:
            favorites = [song for key, song in self.favorites.items() if key != selection]
            self.persist_favorites(favorites)

    def render_favorites(self):
        for child in self.favorite_rows.winfo_children():
            child.destroy()
        query = self.favorite_query.get().strip().casefold()
        visible = {key: song for key, song in self.favorites.items()
                   if query in f"{song['track_name']} {song['artists']}".casefold()}
        if self.selected_favorite.get() not in visible:
            self.selected_favorite.set("")
        for key, song in visible.items():
            self.song_choice(self.favorite_rows, song, self.selected_favorite, key)
        if not self.favorites:
            ttk.Label(self.favorite_rows, text="Add a few songs you love. We will use their audio traits to find your next match.", style="CardMuted.TLabel", wraplength=250).pack(anchor="w", pady=8)
        elif not visible:
            ttk.Label(self.favorite_rows, text="No saved songs match this filter. Your favorites are still saved.", style="CardMuted.TLabel", wraplength=250).pack(anchor="w", pady=8)
        self.visible_favorite_ids = list(visible)
        self.favorite_filter_status.set(f"{len(visible)} of {len(self.favorites)} shown" if query else f"{len(self.favorites)} saved songs")
        self.favorite_title.set(f"Your favorites ({len(self.favorites)})")
        self.install_wheel_binding(self.favorite_rows)
        self.root.after_idle(self.wrap_labels)

    def refresh_favorites(self):
        self.render_favorites()
        self.update_add_buttons()
        self.clear_cards()
        self.scroll_remainder = 0.0
        self.set_controls()

    def clear_cards(self):
        self.stop_scroll()
        self.history_mode = False
        self.displayed_batch = None
        self.displayed_rating = "all"
        self.recommendation_heading.configure(text="Your next discoveries")
        self.view_context.set("Current suggestions")
        self.back_current.pack_forget()
        self.recommendation_views = []
        for widget in self.cards.winfo_children():
            widget.destroy()
        empty = ttk.Frame(self.cards, style="Card.TFrame", padding=24)
        empty.pack(fill="x")
        ttk.Label(empty, text="A little inspiration starts here.", style="Song.TLabel", wraplength=500).pack(anchor="w")
        ttk.Label(empty, text="Choose your favorites above, then click Suggest songs.", style="CardMuted.TLabel", wraplength=500).pack(anchor="w", pady=(7, 0))
        self.install_wheel_binding(self.cards)
        self.root.after_idle(self.wrap_labels)

    def more_songs(self):
        if not self.busy:
            self.stop_scroll()
            self.query.set("")
            self.artist_query.set("")
            self.canvas.yview_moveto(0)
            self.entry.focus_set()
            self.status.set("Search for another favorite, then add it to your list.")

    def recommend(self):
        if self.busy or not self.favorites:
            return
        favorites = list(self.favorites.values())
        ids = list(self.favorites)
        profile = self.profile_id
        fresh = self.fresh_only.get()
        refresh_browser = bool(self.history_panel.winfo_manager())
        rating = self.history_filter.get().lower()
        self.status.set("Finding songs and saving recommendation context...")
        def work():
            effective_favorites = []
            for song in favorites:
                try:
                    effective_favorites.append(self.engine.get_song(song["track_id"]))
                except ValueError:
                    effective_favorites.append(song)
            feedback = self.store.training_feedback(profile)
            exclusions = self.store.recommendation_exclusions(profile, fresh=fresh)
            recommendations = self.engine.recommend(ids, favorite_songs=effective_favorites, feedback=feedback, exclude_ids=exclusions)
            batch = self.store.save_batch(effective_favorites, recommendations, profile_id=profile) if recommendations else None
            if not recommendations:
                self.store.clear_current_recommendations(profile)
            rows = self.store.list_history(profile, rating=rating, limit=31) if refresh_browser else None
            return batch, recommendations, rows
        def done(result):
            batch, songs, rows = result
            empty = "No unseen songs remain. Turn off Fresh suggestions to revisit eligible tracks, or browse history." if fresh else "No songs remain after excluding your favorites and No votes. Review your ratings in history or change your favorites."
            self.show_recommendations((batch, songs), empty_text=empty)
            if fresh:
                self.view_context.set("Fresh suggestions — previously shown songs excluded")
            if rows is not None:
                self.history_offset = 0
                self.set_history_rows(rows)
            if not songs:
                self.status.set(empty)
        self.submit(work, done)

    def show_recommendations(self, result, scroll=True, history=False, empty_text=None):
        self.stop_scroll()
        batch, songs = result
        self.history_mode = history
        self.displayed_batch = batch
        self.displayed_rating = "all"
        self.recommendation_heading.configure(text="Saved discoveries" if history else "Your next discoveries")
        self.view_context.set("Saved recommendation session" if history else "Current suggestions")
        self.back_current.pack_forget()
        if history:
            self.back_current.pack(anchor="w", pady=(0, 12), before=self.cards)
        for widget in self.cards.winfo_children():
            widget.destroy()
        self.recommendation_views = []
        for index, song in enumerate(songs, 1):
            card = ttk.Frame(self.cards, padding=22, style="Card.TFrame")
            card.pack(fill="x", pady=(0, 12))
            card.columnconfigure(0, weight=1)
            ttk.Label(card, text=f"MATCH {index:02}", style="Kicker.TLabel").grid(row=0, column=0, sticky="w")
            ttk.Label(card, text=song.get("display_title", song["track_name"]), style="CardHeading.TLabel", wraplength=500).grid(row=1, column=0, sticky="ew", pady=(7, 2))
            ttk.Label(card, text=song["artists"], style="CardMuted.TLabel", wraplength=500).grid(row=2, column=0, sticky="ew")
            ttk.Label(card, text=self.reason_preview(song), style="Card.TLabel", wraplength=500).grid(row=3, column=0, sticky="ew", pady=(12, 10))
            detail = ttk.Label(card, text=song["reason"], style="CardMuted.TLabel", wraplength=500)
            detail.grid(row=5, column=0, sticky="ew", pady=(0, 12))
            detail.grid_remove()
            footer = ttk.Frame(card, style="Card.TFrame")
            footer.grid(row=6, column=0, sticky="ew", pady=(5, 0))
            vote = song.get("liked")
            response = tk.StringVar(value="Good suggestion?" if vote is None else ("Saved: Yes" if vote else "Saved: No"))
            view = {"card": card, "song": song, "detail": detail, "expanded": False, "buttons": {}, "response": response}
            details_button = ttk.Button(card, text="Why this match?", style="Small.TButton", command=lambda v=view: self.toggle_details(v))
            details_button.grid(row=4, column=0, sticky="w", pady=(0, 10))
            view["details_button"] = details_button
            for label, liked in (("Yes", True), ("No", False)):
                button = ttk.Button(footer, text=label, style="Selected.TButton" if vote is liked else "TButton", command=lambda b=batch, s=song, v=liked, r=response, w=view: self.feedback(b, s, v, r, w))
                button.pack(side="left", padx=(0, 8))
                view["buttons"][liked] = button
            ttk.Label(footer, textvariable=response, style="CardMuted.TLabel").pack(side="left", padx=(4, 0))
            reason_row = ttk.Frame(card, style="Card.TFrame")
            reason_row.grid(row=7, column=0, sticky="ew", pady=(12, 0))
            ttk.Label(reason_row, text="Optional: what missed the mark?", style="CardMuted.TLabel").pack(anchor="w", pady=(0, 4))
            reason_var = tk.StringVar(value=song.get("feedback_reason") or "No reason")
            reason_picker = ttk.Combobox(reason_row, textvariable=reason_var, values=("No reason",) + FEEDBACK_REASONS, state="readonly", width=12)
            reason_picker.pack(fill="x")
            view.update(reason_row=reason_row, reason_var=reason_var, reason_picker=reason_picker)
            reason_picker.bind("<<ComboboxSelected>>", lambda event, b=batch, s=song, r=response, w=view: self.feedback(b, s, False, r, w))
            if vote is not False:
                reason_row.grid_remove()
            self.recommendation_views.append(view)
        if not songs:
            ttk.Label(self.cards, text=empty_text or "No suggestions available. Change your favorites or browse history.", wraplength=800).pack(anchor="w")
        self.install_wheel_binding(self.cards)
        self.root.after_idle(self.wrap_labels)
        if scroll:
            self.root.after_idle(lambda: self.scroll_to_widget(self.recommendation_heading))
        self.scroll_remainder = 0.0
        self.status.set("Suggestions ready. Rate any song, or add more favorites and suggest again.")

    def toggle_details(self, view):
        view["expanded"] = not view["expanded"]
        if view["expanded"]:
            view["detail"].grid()
        else:
            view["detail"].grid_remove()
        view["details_button"].configure(text="Hide details" if view["expanded"] else "Why this match?")
        self.root.after_idle(self.wrap_labels)

    def feedback(self, batch, song, liked, response, view=None):
        if self.busy:
            return
        self.status.set("Saving your feedback...")
        profile = self.profile_id
        reason = view["reason_var"].get() if view and not liked else None
        reason = None if reason == "No reason" else reason
        previous_reason = song.get("feedback_reason")
        historical = self.history_mode
        displayed_rating = self.displayed_rating
        mismatch = historical and displayed_rating != "all" and displayed_rating != ("yes" if liked else "no")
        refresh_browser = bool(self.history_panel.winfo_manager())
        browser_rating, offset = self.history_filter.get().lower(), self.history_offset
        selected_index = self.history_picker.current()
        selected_batch = self.history_rows[selected_index]["batch_id"] if 0 <= selected_index < len(self.history_rows) else None
        def work():
            self.store.save_feedback(batch, song["track_id"], liked, profile_id=profile, reason=reason)
            # The write is committed. A later refresh failure must not make a
            # successfully stored vote appear to have failed or undo its reason.
            try:
                counts = self.store.feedback_counts(profile)
                data = self.store.load_batch(profile, batch, rating=displayed_rating) if mismatch else None
                rows = self.store.list_history(profile, rating=browser_rating, limit=31, offset=offset) if refresh_browser else None
                return counts, data, rows
            except Exception:
                return None, None, None
        def saved(result):
            counts, data, rows = result
            response.set("Saved: Yes" if liked else "Saved: No")
            song["liked"] = liked
            song["feedback_reason"] = reason
            if view:
                for value, button in view["buttons"].items():
                    button.configure(style="Selected.TButton" if value is liked else "TButton")
                view["reason_var"].set(reason or "No reason")
                if liked:
                    view["reason_row"].grid_remove()
                else:
                    view["reason_row"].grid()
            if data:
                self.show_history_batch(data, scroll=False, rating=displayed_rating)
            elif mismatch and view:
                view["card"].destroy()
                self.recommendation_views.remove(view)
                if not self.recommendation_views:
                    ttk.Label(self.cards, text="No songs remain in this filtered view. Reopen a session to refresh it.", wraplength=800).pack(anchor="w")
            if rows is not None:
                self.set_history_rows(rows, selected_batch=selected_batch)
            if counts is None:
                self.status.set("Feedback saved. Totals and history could not refresh; reopen history to retry.")
                self.context_status.set("Your vote is saved. Updated totals are temporarily unavailable.")
            else:
                self.status.set("Feedback saved. You can change your answer using Yes or No.")
                self.update_counts(counts)
            self.root.after_idle(self.wrap_labels)
        def failed():
            if view:
                view["reason_var"].set(previous_reason or "No reason")
        self.submit(work, saved, on_error=failed)

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.executor.shutdown(wait=False, cancel_futures=True)
        # This app owns the root. Cancel scheduled polling/layout callbacks
        # before Tk deletes their commands during window destruction.
        for callback_id in self.root.tk.splitlist(self.root.tk.call("after", "info")):
            self.root.after_cancel(callback_id)
        self.root.destroy()


def main():
    root = tk.Tk()
    MusicMatchApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
