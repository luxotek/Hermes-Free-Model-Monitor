#!/usr/bin/env python3w
"""Hermes Free Model Monitor - tiny window that follows the installed Hermes skin."""
import datetime
import json
import os
import re
import threading
import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from tkinter import messagebox, ttk

import alerts
import bubbles
import hermes_state
import nous_core
import theme

APP_NAME = "HFMM-beta"

FONT = "Segoe UI"
SZ_TITLE = 20
SZ_BODY = 13
SZ_TREE = 14
SZ_HEAD = 13

COLS = ("Model", "Context", "Inputs", "Output", "Released", "Flags", "Source")
WIDTHS = {"Model": 360, "Context": 110, "Inputs": 160, "Output": 110,
          "Released": 110, "Flags": 200, "Source": 120}
CFG_COLS = ("Role", "Model", "Provider", "Context", "Flags", "Temp", "Status", "Notes")
CFG_WIDTHS = {
    "Role": 190, "Model": 340, "Provider": 90, "Context": 110,
    "Flags": 200, "Temp": 150, "Status": 100, "Notes": 240,
}

SZ_INFO = 14

MODELS_REFRESH_MS = 15 * 60 * 1000
DEEP_REFRESH_MS = 4 * 60 * 60 * 1000
POLL_MS = 3000
UI_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui_state.json")


def load_ui_state():
    try:
        with open(UI_FILE, encoding="utf-8") as fh:
            state = json.load(fh)
        if isinstance(state, dict):
            return state
    except (OSError, ValueError):
        pass
    return {}


def save_ui_state(state):
    try:
        with open(UI_FILE, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
    except OSError:
        pass


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.minsize(960, 540)
        self.ui = load_ui_state()
        self._apply_geometry()
        self._geom_after_id = None
        self.bind("<Configure>", self._on_resize)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.models = []
        self.cfg_rows = []
        self.fallback_entries = []
        self._fallback_busy = False
        self._fb_rows = []
        self._fb_chain = {}
        self._drag_fb = None
        self.usage_data = {"counts": {}, "fallbacks": [], "last": None}
        self.palette = dict(theme.FALLBACK_PALETTE)
        self.meta = {}
        self.catalog_meta = {}
        self.catalog_lookup = {}
        self.choice = theme.load_choice()
        self.skins = ["Auto (follow Hermes)"] + theme.skin_names()
        self.selected_slug = None
        self._last_alerted_active = None
        self._flash_after_id = None
        self.bubbles_var = tk.BooleanVar(value=bool(self.ui.get("bubbles")))
        self.alert_history = []
        self._empty_frames = {}
        self.bubbles = None
        self._busy = False
        self._models_after_id = None
        self._deep_after_id = None
        self._poll_id = None
        self.combo_var = tk.StringVar()
        self.auto_models_var = tk.BooleanVar(value=bool(self.ui.get("auto_models")))
        self.deep_var = tk.BooleanVar(value=bool(self.ui.get("deep")))
        self._measure_font = tkfont.Font(family=FONT, size=SZ_TREE)

        palette, meta = theme.resolve(self.choice)
        self.palette, self.meta = palette, meta
        self.configure(bg=self.palette["bg"])
        self._style()
        self.bubbles = bubbles.BubbleStack(
            self, lambda: self.palette, lambda: bool(self.bubbles_var.get()),
            anchor=lambda: getattr(self, "nb", None),
        )
        self._build_ui()
        self._sync_combo()
        self.after(200, self.refresh)
        self._apply_timers()
        self._schedule_poll()
        self._scroll_sync_after_id = None
        self.after(1000, self._scroll_sync_tick)

    # ---------- window geometry ----------

    def _apply_geometry(self):
        """Reopen where (and how big) the window was last time, else size to screen."""
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        default_w = max(1100, min(int(screen_w * 0.78), 1400))
        default_h = max(640, min(int(screen_h * 0.85), 860))
        match = re.match(r"^(\d+)x(\d+)(?:([+-]\d+)([+-]\d+))?$", str(self.ui.get("geometry") or ""))
        if not match:
            self.geometry(f"{default_w}x{default_h}"
                          f"+{(screen_w - default_w) // 2}"
                          f"+{max((screen_h - default_h) // 2, 0)}")
            return
        width = max(960, int(match.group(1)))
        height = max(540, int(match.group(2)))
        pos_x = int(match.group(3)) if match.group(3) else (screen_w - width) // 2
        pos_y = int(match.group(4)) if match.group(4) else max((screen_h - height) // 2, 0)
        # A saved spot on a monitor that no longer exists: center instead.
        if not (0 <= pos_x <= screen_w - 200 and 0 <= pos_y <= screen_h - 120):
            pos_x, pos_y = (screen_w - width) // 2, max((screen_h - height) // 2, 0)
        self.geometry(f"{width}x{height}+{pos_x}+{pos_y}")

    def _on_resize(self, event=None):
        if event is not None and event.widget is not self:
            return
        if self.state() != "normal":
            return
        if self._geom_after_id:
            self.after_cancel(self._geom_after_id)
        self._geom_after_id = self.after(500, self._save_geometry)

    def _save_geometry(self):
        self._geom_after_id = None
        try:
            if self.state() != "normal":
                return
            self.ui["geometry"] = self.geometry()
            save_ui_state(self.ui)
        except Exception:
            pass

    def _on_close(self):
        self._save_geometry()
        self.destroy()

    # ---------- theming ----------

    def _c(self, key):
        return self.palette.get(key, theme.FALLBACK_PALETTE[key])

    def _style(self):
        p = self.palette
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "Treeview", background=p["card"], foreground=p["fg"],
            fieldbackground=p["card"], borderwidth=0, rowheight=38,
            font=(FONT, SZ_TREE),
        )
        style.configure(
            "Treeview.Heading", background=p["head_bg"], foreground=p["head_fg"],
            relief="flat", font=("Segoe UI Semibold", SZ_HEAD), padding=(8, 6),
        )
        style.map(
            "Treeview",
            background=[("selected", p["selection"])],
            foreground=[("selected", p["fg"])],
        )
        style.configure("TButton", background=p["head_bg"], foreground=p["fg"], borderwidth=0, padding=12)
        style.map("TButton", background=[("active", p["border"])])
        style.configure("TCheckbutton", background=p["bg"], foreground=p["dim"], font=(FONT, SZ_INFO))
        style.map("TCheckbutton", background=[("active", p["bg"])])
        style.configure("Vertical.TScrollbar", background=p["head_bg"], troughcolor=p["bg"], borderwidth=0)
        style.configure(
            "TCombobox", fieldbackground=p["card"], background=p["head_bg"],
            foreground=p["fg"], arrowcolor=p["fg"],
        )
        style.map("TCombobox", fieldbackground=[("readonly", p["card"])], foreground=[("readonly", p["fg"])])
        style.configure("TNotebook", background=p["bg"], borderwidth=0)
        style.configure("TNotebook.Tab", background=p["head_bg"], foreground=p["dim"], padding=(16, 8))
        style.map(
            "TNotebook.Tab",
            background=[("selected", p["card"])],
            foreground=[("selected", p["fg"])],
        )

    def apply_theme(self, palette, meta=None):
        self.palette = palette
        if meta is not None:
            self.meta = meta
        self.configure(bg=self.palette["bg"])
        self._style()
        self._rebuild()

    def _rebuild(self):
        self._build_ui()
        self._sync_combo()
        for model in self.models:
            self._insert(model)
        self._render_config(self.cfg_rows, self.usage_data)
        if hasattr(self, "tree") and hasattr(self.tree_hscroll, "winfo_exists"):
            self._autofit_columns(self.tree, self.tree_hscroll, self.tree_vscroll)

    def _sync_combo(self):
        label = "Auto (follow Hermes)"
        if self.choice.get("mode") == "skin":
            label = self.choice.get("name", label)
        else:
            followed = theme.desktop_theme_name() or theme._active_name()
            if followed:
                label = f"Auto ({followed})"
        if self.combo_var.get() != label:
            self.combo_var.set(label)

    def _on_skin_select(self, _event=None):
        picked = self.combo_var.get()
        choice = (
            {"mode": "auto"}
            if picked.startswith("Auto")
            else {"mode": "skin", "name": picked}
        )
        if choice == self.choice:
            return
        self.choice = choice
        theme.save_choice(choice)
        self.after(20, self._reload_theme)

    def _reload_theme(self):
        palette, meta = theme.resolve(self.choice)
        self.apply_theme(palette, meta)
        source = self.meta.get("source", "?")
        skin = self.meta.get("skin", "?")
        self._flash_status(f"Theme: {skin} ({'live' if source == 'engine' else source})")

    def _schedule_poll(self):
        if self._poll_id:
            self.after_cancel(self._poll_id)
        self._poll_id = self.after(POLL_MS, self._poll_tick)

    def _poll_tick(self):
        if self.choice.get("mode") == "auto":
            palette, meta = theme.resolve(self.choice)
            if palette != self.palette:
                self.apply_theme(palette, meta)
            self._sync_combo()
        self._schedule_poll()

    # ---------- ui ----------

    def _build_ui(self):
        for widget in list(self.winfo_children()):
            widget.destroy()
        self._build_toolbar()
        self._build_notebook()
        self._build_detail_panel()
        self._build_status()

    def _build_toolbar(self):
        p = self.palette
        bar = tk.Frame(self, bg=p["bg"])
        bar.pack(fill="x", padx=14, pady=(14, 4))
        # Row 0: title + buttons. The title is the only stretchable column, so a
        # narrow window clips the title instead of pushing buttons off the bar.
        # Row 1: the status line gets the full width.
        bar.columnconfigure(0, weight=1)

        tk.Label(bar, text=APP_NAME, bg=p["bg"], fg=p["fg"],
                 font=("Segoe UI Semibold", SZ_TITLE)).grid(row=0, column=0, sticky="w")
        ttk.Button(bar, text="Refresh", command=self.refresh).grid(
            row=0, column=1, padx=(0, 6), sticky="e")
        self.set_main_btn = ttk.Button(bar, text="Set main model", command=self.set_main_model)
        self.set_main_btn.state(["disabled"])
        self.set_main_btn.grid(row=0, column=2, padx=(0, 6), sticky="e")
        combo = ttk.Combobox(
            bar, textvariable=self.combo_var, values=self.skins,
            state="readonly", width=24,
        )
        combo.bind("<<ComboboxSelected>>", self._on_skin_select)
        combo.grid(row=0, column=3, padx=(0, 6), sticky="e")
        ttk.Button(bar, text="Settings", command=self.open_settings).grid(
            row=0, column=4, sticky="e")

        self.info = tk.Label(bar, text="", bg=p["bg"], fg=p["dim"],
                             font=(FONT, SZ_INFO), anchor="w")
        self.info.grid(row=1, column=0, columnspan=5, sticky="w", pady=(2, 0))

    def _build_notebook(self):
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=14, pady=(4, 2))
        tab_free = tk.Frame(self.nb, bg=self._c("bg"))
        tab_cfg = tk.Frame(self.nb, bg=self._c("bg"))
        self.nb.add(tab_free, text="Free models")
        self.nb.add(tab_cfg, text="Hermes config")
        self._build_catalog_tab(tab_free)
        self._build_config_tab(tab_cfg)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree2.bind("<<TreeviewSelect>>", self._on_tree_select)

    def _build_detail_panel(self):
        p = self.palette
        wrap = tk.Frame(self, bg=p["border"])
        wrap.pack(fill="x", padx=14, pady=(2, 2))
        inner = tk.Frame(wrap, bg=p["card"])
        inner.pack(fill="x")
        self.detail_title = tk.Label(
            inner, text="Select a row to see its full details.",
            bg=p["card"], fg=p["dim"], font=("Segoe UI Semibold", SZ_INFO),
            anchor="w", padx=12, pady=8,
        )
        self.detail_title.pack(fill="x")
        self.detail_chips = tk.Label(
            inner, text="", bg=p["card"], fg=p["fg"], font=(FONT, SZ_INFO),
            anchor="w", justify="left", padx=12, pady=3,
        )
        self.detail_chips.pack(fill="x")
        self.detail_body = tk.Label(
            inner, text="", bg=p["card"], fg=p["fg"], font=(FONT, SZ_INFO - 1),
            anchor="w", justify="left", padx=12, pady=1,
        )
        self.detail_body.pack(fill="x")
        self.detail_scores = tk.Label(
            inner, text="", bg=p["card"], fg=p["dim"], font=(FONT, SZ_INFO - 1),
            anchor="w", justify="left", padx=12, pady=6,
        )
        self.detail_scores.pack(fill="x")

    def _build_catalog_tab(self, parent):
        wrap = tk.Frame(parent, bg=self._c("bg"))
        wrap.pack(fill="both", expand=True, padx=0, pady=(2, 0))

        self.tree = ttk.Treeview(wrap, columns=COLS, show="headings", height=12)
        for col in COLS:
            self.tree.heading(col, text=col, anchor="w")
            self.tree.column(col, width=WIDTHS[col], anchor="w")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda _e: self.copy_selected())
        self.tree.bind("<Button-3>", self._on_free_rclick)

        self.tree_vscroll = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree_vscroll.pack(side="right", fill="y")
        self.tree_hscroll = ttk.Scrollbar(wrap, orient="horizontal", command=self.tree.xview)
        self.tree_hscroll.pack(side="bottom", fill="x")
        self.tree.configure(yscrollcommand=self.tree_vscroll.set, xscrollcommand=self.tree_hscroll.set)
        self.tree.bind(
            "<Configure>",
            lambda _e: self._sync_vscroll(self.tree, self.tree_vscroll),
            add="+",
        )

    def _build_config_tab(self, parent):
        p = self.palette
        wrap = tk.Frame(parent, bg=p["bg"])
        wrap.pack(fill="both", expand=True)

        self.usage = tk.Label(
            wrap, text="Recent API calls: ...", bg=p["bg"], fg=p["dim"],
            font=(FONT, SZ_INFO), anchor="w",
        )
        self.usage.pack(fill="x", padx=6, pady=(4, 2))

        inner = tk.Frame(wrap, bg=p["bg"])
        inner.pack(fill="both", expand=True)

        self.tree2 = ttk.Treeview(inner, columns=CFG_COLS, show="headings", height=10)
        for col in CFG_COLS:
            self.tree2.heading(col, text=col, anchor="w")
            self.tree2.column(col, width=CFG_WIDTHS[col], anchor="w")
        self.tree2.pack(side="left", fill="both", expand=True)
        self.tree2.bind("<Double-1>", lambda _e: self.copy_row(self.tree2))
        self.tree2.bind("<Button-1>", self._on_cfg_press)
        self.tree2.bind("<B1-Motion>", self._on_cfg_motion)
        self.tree2.bind("<ButtonRelease-1>", self._on_cfg_release)
        self.tree2.bind("<Motion>", self._on_cfg_hover)
        self.tree2.bind("<Button-3>", self._on_cfg_rclick)

        self.tree2.tag_configure("free", foreground=p["ok"])
        self.tree2.tag_configure("paid", foreground=p["warn"])
        self.tree2.tag_configure("missing", foreground=p["error"])
        self.tree2.tag_configure("dragging", background=p["accent"], foreground=p["fg"])

        self.tree2_vscroll = ttk.Scrollbar(inner, orient="vertical", command=self.tree2.yview)
        self.tree2_vscroll.pack(side="right", fill="y")
        self.tree2_hscroll = ttk.Scrollbar(inner, orient="horizontal", command=self.tree2.xview)
        self.tree2_hscroll.pack(side="bottom", fill="x")
        self.tree2.configure(yscrollcommand=self.tree2_vscroll.set, xscrollcommand=self.tree2_hscroll.set)
        self.tree2.bind(
            "<Configure>",
            lambda _e: self._sync_vscroll(self.tree2, self.tree2_vscroll),
            add="+",
        )

    def _build_status(self):
        self.status = tk.Label(
            self, text="Connecting…", bg=self._c("bg"), fg=self._c("dim"),
            font=(FONT, SZ_INFO), anchor="w",
        )
        self.status.pack(fill="x", padx=16, pady=(2, 12))

    def _refresh_status(self):
        if not hasattr(self, "status"):
            return
        parts = []
        if self.catalog_meta:
            parts.append(f"{self.catalog_meta.get('free_count')} free models of {self.catalog_meta.get('catalog_rows')} total")
        if hasattr(self, "last_models"):
            parts.append(f"catalog updated {self.last_models}")
        if hasattr(self, "last_deep"):
            parts.append(f"Hermes config checked {self.last_deep}")
        self.status.configure(text="   ·   ".join(parts) or "Connecting…")

    def _flash_status(self, message, ms=2600):
        if not hasattr(self, "status"):
            return
        self.status.configure(text=message, fg=self._c("ok"))
        if getattr(self, "_flash_after_id", None):
            self.after_cancel(self._flash_after_id)
        self._flash_after_id = self.after(ms, self._refresh_status)

    # ---------- settings / about ----------

    def open_settings(self):
        p = self.palette
        win = tk.Toplevel(self)
        win.title(f"Settings — {APP_NAME}")
        win.configure(bg=p["bg"])
        win.resizable(False, False)
        win.transient(self)
        win.grab_set()

        sec = tk.Label(win, text="Preferences", bg=p["bg"], fg=p["accent"],
                       font=("Segoe UI Semibold", 14), anchor="w")
        sec.pack(fill="x", padx=24, pady=(18, 6))
        prefs = tk.Frame(win, bg=p["bg"])
        prefs.pack(fill="x", padx=28)
        ttk.Checkbutton(prefs, text="Auto models (15 min)", variable=self.auto_models_var,
                        command=self._apply_timers).pack(anchor="w", pady=2)
        ttk.Checkbutton(prefs, text="Deep check (4 h)", variable=self.deep_var,
                        command=self._apply_timers).pack(anchor="w", pady=2)
        ttk.Checkbutton(prefs, text="Bubbles", variable=self.bubbles_var,
                        command=self._apply_timers).pack(anchor="w", pady=2)

        sec = tk.Label(win, text="Alert history", bg=p["bg"], fg=p["accent"],
                       font=("Segoe UI Semibold", 14), anchor="w")
        sec.pack(fill="x", padx=24, pady=(14, 6))
        hist = tk.Frame(win, bg=p["border"])
        hist.pack(fill="both", expand=True, padx=24)
        inner = tk.Frame(hist, bg=p["card"])
        inner.pack(fill="both", expand=True)
        text = tk.Text(inner, height=7, bg=p["card"], fg=p["fg"], font=(FONT, 12),
                       relief="flat", wrap="word", padx=8, pady=6)
        text.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(inner, orient="vertical", command=text.yview)
        sb.pack(side="right", fill="y")
        text.configure(yscrollcommand=sb.set)
        for level, color_key in (("critical", "error"), ("warn", "warn"), ("ok", "ok")):
            text.tag_configure(level, foreground=p[color_key])
        entries = list(reversed(self.alert_history[-20:]))
        if not entries:
            text.insert("end", "No alerts yet.\n")
        for entry in entries:
            text.insert("end", f"{entry['ts']}  {entry['text']}\n", entry["level"])
        text.configure(state="disabled")

        sec = tk.Label(win, text="About", bg=p["bg"], fg=p["accent"],
                       font=("Segoe UI Semibold", 14), anchor="w")
        sec.pack(fill="x", padx=24, pady=(14, 6))
        about = tk.Frame(win, bg=p["bg"])
        about.pack(fill="x", padx=28)
        tk.Label(about, text="Created by luxotek", bg=p["bg"], fg=p["fg"],
                 font=("Segoe UI Semibold", 13)).pack(anchor="w")
        for line in (
            "Checks Hermes's 400+ model list to find which free models are live",
            "right now, so you can set a reliable main model and fallback chain.",
            "Built with AI assistance (Hermes Agent) — see NOTICE.md.",
            "Free for personal use; share and modify with credit + AI notice.",
            "Not for sale by others — luxotek keeps commercial rights. See LICENSE.",
        ):
            tk.Label(about, text=line, bg=p["bg"], fg=p["dim"], font=(FONT, 12),
                     anchor="w", justify="left").pack(fill="x")
        links = tk.Frame(about, bg=p["bg"])
        links.pack(fill="x", pady=(6, 0))
        for label in ("LICENSE", "NOTICE.md"):
            link = tk.Label(links, text=label, bg=p["bg"], fg=p["accent"],
                            font=("Segoe UI Semibold", 12), cursor="hand2")
            link.pack(side="left", padx=(0, 14))
            link.bind("<Button-1>", lambda _e, f=label: self._open_doc(f))

        ttk.Button(win, text="Close", command=win.destroy).pack(pady=(12, 16))
        win.bind("<Escape>", lambda _e: win.destroy())
        win.update_idletasks()
        width = max(win.winfo_width(), 540)
        height = min(win.winfo_height(), self.winfo_screenheight() - 80)
        x = self.winfo_rootx() + (self.winfo_width() - width) // 2
        y = self.winfo_rooty() + max((self.winfo_height() - height) // 2, 0)
        win.geometry(f"{width}x{height}+{x}+{y}")

    def _open_doc(self, filename):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
        try:
            os.startfile(path)
        except Exception:
            webbrowser.open("https://github.com/luxotek/Hermes-Free-Model-Monitor")

    # ---------- column fitting ----------

    def _autofit_columns(self, tree, hscroll, vscroll=None):
        font = getattr(self, "_measure_font", None) or tkfont.Font(family=FONT, size=SZ_TREE)
        cols = tree["columns"]
        items = tree.get_children()
        total = 0
        for index, col in enumerate(cols):
            width = font.measure(str(tree.heading(col)["text"])) + 24
            for item in items:
                values = tree.item(item)["values"]
                if index < len(values):
                    width = max(width, font.measure(str(values[index])) + 24)
            cap = 460 if col in ("Model", "Detail") else 300
            width = min(max(width, 64), cap)
            tree.column(col, width=width, stretch=False)
            total += width
        tree.update_idletasks()
        viewport = tree.winfo_width() - 4
        if viewport > 1 and total <= viewport:
            hscroll.pack_forget()
        else:
            hscroll.pack(side="bottom", fill="x")
        if vscroll is not None:
            self._sync_vscroll(tree, vscroll)

    def _sync_vscroll(self, tree, vscroll):
        if tree is None or vscroll is None:
            return
        try:
            if not tree.winfo_exists() or not tree.winfo_ismapped():
                return
        except Exception:
            return
        tree.update_idletasks()
        first, last = tree.yview()
        need = last - first < 0.999
        if need == bool(vscroll.winfo_ismapped()):
            return
        if need:
            vscroll.pack(side="right", fill="y")
        else:
            vscroll.pack_forget()

    def _sync_hscroll(self, tree, hscroll):
        if tree is None or hscroll is None:
            return
        try:
            if not tree.winfo_exists() or not tree.winfo_ismapped():
                return
        except Exception:
            return
        total = sum(tree.column(col, "width") for col in tree["columns"])
        viewport = tree.winfo_width() - 4
        need = viewport <= 1 or total > viewport
        if need == bool(hscroll.winfo_ismapped()):
            return
        if need:
            hscroll.pack(side="bottom", fill="x")
        else:
            hscroll.pack_forget()

    def _scroll_sync_tick(self):
        """Keep scrollbars visible only while they are actually needed."""
        pairs = (
            (getattr(self, "tree", None), getattr(self, "tree_vscroll", None), getattr(self, "tree_hscroll", None)),
            (getattr(self, "tree2", None), getattr(self, "tree2_vscroll", None), getattr(self, "tree2_hscroll", None)),
        )
        for tree, vscroll, hscroll in pairs:
            self._sync_vscroll(tree, vscroll)
            self._sync_hscroll(tree, hscroll)
        self._scroll_sync_after_id = self.after(2000, self._scroll_sync_tick)

    # ---------- empty states / bubbles ----------

    def _empty_overlay(self, key, parent, title, lines):
        self._clear_empty(key)
        p = self.palette
        frame = tk.Frame(parent, bg=p["bg"])
        tk.Label(frame, text=title, bg=p["bg"], fg=p["fg"],
                 font=("Segoe UI Semibold", 15)).pack(pady=(0, 4))
        for line in lines:
            tk.Label(frame, text=line, bg=p["bg"], fg=p["dim"],
                     font=(FONT, SZ_INFO)).pack()
        frame.place(in_=parent, relx=0.5, rely=0.5, anchor="center")
        self._empty_frames[key] = frame

    def _clear_empty(self, key):
        frame = self._empty_frames.pop(key, None)
        if frame is not None:
            try:
                frame.destroy()
            except Exception:
                pass

    def _record_history(self, level, text):
        ts = datetime.datetime.now().strftime("%H:%M")
        self.alert_history.append({"ts": ts, "level": level, "text": text})
        self.alert_history = self.alert_history[-20:]

    def _notify(self, title, message, level="info"):
        if self.bubbles is not None:
            self.bubbles.show(title, message, level)

    # ---------- data ----------

    def refresh(self):
        self._fetch(models=True, deep=True)

    def refresh_models(self):
        self._fetch(models=True, deep=False)

    def refresh_deep(self):
        self._fetch(models=False, deep=True)

    def _fetch(self, models=True, deep=True):
        if self._busy:
            return
        self._busy = True
        self.status.configure(text="Checking...", fg=self._c("dim"))

        def work():
            models_out = None
            meta_out = None
            cfg_rows = []
            usage = None
            fb_entries = []
            if models:
                try:
                    models_out, meta_out = nous_core.fetch_free_models()
                except Exception as exc:  # noqa: BLE001
                    self.after(0, lambda: self._show_error(exc))
                    return
            if deep:
                try:
                    cfg_rows = hermes_state.configured_models()
                    usage = hermes_state.recent_usage()
                except Exception:
                    cfg_rows, usage = [], {"counts": {}, "fallbacks": [], "last": None}
                try:
                    fb_entries = hermes_state.fallback_chain()
                except Exception:
                    fb_entries = []
            self.after(0, lambda: self._show(models_out, meta_out, cfg_rows, usage, fb_entries))

        threading.Thread(target=work, daemon=True).start()

    def _classify(self, slug, free_names, catalog_ids):
        if slug in free_names:
            return "free", "in live free list"
        base = slug.split(":", 1)[0]
        if slug in catalog_ids or base in catalog_ids:
            return "paid", "listed, not free"
        return "missing", "not in catalog (dead?)"

    def _model_info(self, slug):
        """Context/flags for a configured model: catalog entry, else free row."""
        info = self.catalog_lookup.get(slug)
        if info is None and slug.endswith(":free"):
            info = self.catalog_lookup.get(slug[: -len(":free")])
        if info is None:
            for model in self.models:
                if model["name"] == slug:
                    return model
        return info or {}

    @staticmethod
    def _flags_text(info):
        flags = [name for name in ("vision", "video", "compaction") if info.get(name)]
        return ", ".join(flags) or "-"

    @staticmethod
    def _temp_text(info):
        """Lifecycle column: preview/alpha/beta/exp marker and/or API end date."""
        temp = info.get("temp") or ""
        end = info.get("end") or ""
        if temp and end:
            return f"{temp} · ends {end}"
        if temp:
            return temp
        if end:
            return f"ends {end}"
        return "-"

    @staticmethod
    def _model_detail(info, extra_bits=None, lifecycle=False):
        """Facts for the detail panel that are not already columns."""
        extra = (info or {}).get("extra") or {}
        bits = list(extra_bits or [])
        if extra.get("moderated") is True:
            bits.append("moderated")
        reasoning = extra.get("reasoning")
        if reasoning:
            bits.append({"mandatory": "reasoning mandatory",
                          "default-on": "reasoning default-on"}.get(
                              reasoning, "reasoning optional"))
        if extra.get("synthesized"):
            bits.append("synthesized free tier")
        if extra.get("cutoff"):
            bits.append(f"cutoff {extra['cutoff']}")
        if extra.get("hf"):
            bits.append(f"hf {extra['hf']}")
        if lifecycle:
            marker = App._temp_text(info)
            if marker != "-":
                bits.append(marker)
        chips = "   ·   ".join(bits) or "No extra flags reported"

        body = extra.get("description") or "No description reported."
        if len(body) > 320:
            body = body[:317].rstrip() + "…"

        analysis = extra.get("aa") or {}
        scores = "   ·   ".join(
            f"{key.replace('_index', '')} {analysis[key]}"
            for key in ("intelligence_index", "coding_index", "agentic_index")
            if analysis.get(key) is not None
        )
        return chips, body, (f"AA   {scores}" if scores else "")

    @staticmethod
    def _released_text(info):
        """Release date from the catalog's `created` timestamp."""
        ts = info.get("created")
        if not ts:
            return "-"
        try:
            return datetime.datetime.fromtimestamp(int(ts), datetime.UTC).strftime("%Y-%m-%d")
        except (TypeError, ValueError, OSError):
            return "-"

    def _insert(self, model):
        flags = []
        if model["vision"]:
            flags.append("vision")
        if model["video"]:
            flags.append("video")
        if model["compaction"]:
            flags.append("compaction")
        ctx = model["context"]
        out = model.get("output")
        self.tree.insert(
            "", "end",
            values=(
                model["name"],
                f"{ctx:,}" if ctx else "?",
                model["inputs"],
                f"{out:,}" if out else "?",
                self._released_text(model),
                ", ".join(flags) or "-",
                model["source"],
            ),
        )

    def _render_config(self, rows, usage):
        self.cfg_rows = rows
        self.usage_data = usage
        if not hasattr(self, "tree2"):
            return
        self.tree2.delete(*self.tree2.get_children())
        free_names = {m["name"] for m in self.models}
        catalog_ids = set(self.catalog_meta.get("catalog_ids", []))
        for row in rows:
            status, detail = self._classify(row["model"], free_names, catalog_ids)
            info = self._model_info(row["model"])
            context = info.get("context")
            self.tree2.insert(
                "", "end",
                values=(
                    row["role"], row["model"], row["provider"],
                    f"{context:,}" if context else "?",
                    self._flags_text(info),
                    self._temp_text(info),
                    status.upper(), detail,
                ),
                tags=(status,),
            )

        # Fallback rows only: remember which tree row is which fallback_providers slot
        # so they can be dragged into a new order and removed by right-click.
        self._fb_rows = []
        self._fb_chain = {}
        for item in self.tree2.get_children():
            role = str(self.tree2.item(item)["values"][0])
            if role.startswith("fallback #"):
                try:
                    self._fb_chain[item] = int(role.split("#", 1)[1]) - 1
                except ValueError:
                    continue
                self._fb_rows.append(item)

        counts = usage.get("counts", {})
        top = ", ".join(f"{k} ×{v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1])[:4])
        text = f"Recent API calls: {top or 'none'}"
        if usage.get("last"):
            text += f" · last: {usage['last']}"
        fallbacks = usage.get("fallbacks") or []
        if fallbacks:
            text += f" · fallbacks fired: {len(fallbacks)}"
        self.usage.configure(text=text)

        if rows:
            self._clear_empty("config")
        elif getattr(self, "_data_loaded", False) and hasattr(self, "tree2"):
            self._empty_overlay(
                "config", self.tree2.master,
                "No configured models found",
                ["Nothing returned for model.default, auxiliary pins, or fallbacks.",
                 "Tip: anything pinned here is classified FREE / PAID / MISSING."],
            )
        self._autofit_columns(self.tree2, self.tree2_hscroll, self.tree2_vscroll)

    def _show(self, models, meta, cfg_rows, usage, fb_entries=None):
        self._busy = False
        if fb_entries is not None:
            self.fallback_entries = fb_entries
        stamp = datetime.datetime.now().strftime("%H:%M")
        if models is not None:
            self.models = models
            self.meta = meta
            self.catalog_meta = meta
            self.catalog_lookup = (meta or {}).get("catalog_lookup", {})
            if hasattr(self, "tree"):
                self.tree.delete(*self.tree.get_children())
                for model in models:
                    self._insert(model)
                if models:
                    self._clear_empty("models")
                else:
                    self._empty_overlay(
                        "models", self.tree.master,
                        "No free models right now",
                        ["The Portal + inference union came back empty.",
                         "Tip: check your login with `hermes setup`, then hit Refresh."],
                    )
                self._autofit_columns(self.tree, self.tree_hscroll, self.tree_vscroll)
            self.last_models = stamp
        if usage is not None:
            self._render_config(cfg_rows, usage)
            self._data_loaded = True
            self.last_deep = stamp
            self._evaluate_alerts(cfg_rows, usage, stamp)
            self._evaluate_active_alert(usage)

        self._refresh_status()
        self.info.configure(text="account: free tier")

    def _evaluate_alerts(self, cfg_rows, usage, stamp):
        free_names = {m["name"] for m in self.models}
        catalog_ids = set(self.catalog_meta.get("catalog_ids", []))
        new_alerts, current = alerts.compute_alerts(
            self.ui.get("statuses", {}), cfg_rows, free_names, catalog_ids
        )
        if new_alerts:
            self.ui["statuses"] = current
            save_ui_state(self.ui)
            alerts.flash_taskbar(self)
            for alert in new_alerts:
                self._record_history(alert["level"], alert["text"])
                self._notify("Model alert", alert["text"], alert["level"])

    def _evaluate_active_alert(self, usage):
        last = usage.get("last")
        if not last:
            self._last_alerted_active = None
            return
        if last not in self.models and last not in self.catalog_meta.get("catalog_ids", []):
            if last != self._last_alerted_active:
                text = f"Active model {last} is no longer available"
                self._record_history("critical", text)
                self._notify("Active model gone", text, "critical")
                self._last_alerted_active = last

    def _on_tree_select(self, event=None):
        tree = getattr(event, "widget", None) or getattr(self, "tree", None)
        if tree is None:
            return
        try:
            if not tree.winfo_exists():
                return
        except Exception:
            return
        sel = tree.selection()
        if not sel:
            return
        values = tree.item(sel[0])["values"]
        title = ""
        chips = ""
        color = None
        chips = body = scores = ""
        if tree is self.tree:
            self.selected_slug = values[0]
            info = next((m for m in self.models if m["name"] == values[0]), None)
            title = values[0]
            chips, body, scores = self._model_detail(info, lifecycle=True)
        elif tree is self.tree2:
            self.selected_slug = values[1]
            status = values[6].lower()
            color = {"free": self._c("ok"), "paid": self._c("warn"), "missing": self._c("error")}.get(status)
            title = f"{values[0]}  →  {values[1]}"
            note = values[7]
            chips, body, scores = self._model_detail(
                self._model_info(values[1]), extra_bits=[f"status {status}"])
            if note and note != "-":
                body = f"{body}\n{note}"

        if hasattr(self, "detail_title"):
            self.detail_title.configure(
                text=title or "Select a row to see its full details.",
                fg=color if color else (self._c("fg") if title else self._c("dim")),
            )
            width = max(self.winfo_width() - 48, 320)
            self.detail_chips.configure(text=chips, wraplength=width)
            for label, text in ((self.detail_body, body), (self.detail_scores, scores)):
                label.configure(text=text, wraplength=width)
                if text:
                    label.pack(fill="x")
                else:
                    label.pack_forget()
        if self.set_main_btn is not None:
            self.set_main_btn.state(["!disabled"])

    def _show_error(self, error):
        self._busy = False
        if getattr(self, "_flash_after_id", None):
            self.after_cancel(self._flash_after_id)
        self.status.configure(text=f"Error: {error}", fg=self._c("error"))
        self.info.configure(text="")
        self._notify("Refresh failed", str(error)[:160], "critical")

    def set_main_model(self):
        slug = self.selected_slug
        if not slug:
            return
        free_names = {m["name"] for m in self.models}
        if slug not in free_names:
            messagebox.showwarning(
                "No model selected", f"{slug} isn't on the live free model list.\nPick a model in the Free models table."
            )
            return
        if not messagebox.askyesno(
            "Set main model",
            f"Set Hermes main model to:\n\n{slug}\n\nHermes picks it up from the next turn.\n\nFor this chat only: /model {slug}",
        ):
            return
        try:
            proc = hermes_state.run_hermes(["config", "set", "model.default", slug], timeout=30)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Set main model failed", str(exc))
            self._flash_status("Set main model failed")
            return
        if proc.returncode == 0:
            self._flash_status(f"Main model set to {slug}")
            self.refresh_deep()
        else:
            messagebox.showerror("Set main model failed", (proc.stderr or proc.stdout or "unknown error").strip())
            self._flash_status("Set main model failed")

    def copy_selected(self):
        tree = self.tree
        if not tree.selection():
            return
        vals = tree.item(tree.selection()[0])["values"]
        self.clipboard_clear()
        self.clipboard_append(vals[0])
        self.update()
        self._flash_status("Copied: " + vals[0])

    def copy_row(self, tree):
        if not tree.selection():
            return
        vals = tree.item(tree.selection()[0])["values"]
        self.clipboard_clear()
        self.clipboard_append(vals[1])
        self.update()
        self._flash_status("Copied: " + vals[1])

    # ---------- fallback chain editing ----------

    def _on_free_rclick(self, event):
        """Right-click selects the row under the pointer, then opens the context menu."""
        row = self.tree.identify_row(event.y)
        if not row:
            return
        self.tree.selection_set(row)
        self.tree.focus_set()
        self.selected_slug = self.tree.item(row)["values"][0]
        self._popup_free_menu(event)

    def _menu(self, parent=None):
        return tk.Menu(
            parent or self, tearoff=0,
            bg=self._c("card"), fg=self._c("fg"),
            activebackground=self._c("accent"), activeforeground=self._c("fg"),
            relief="flat", borderwidth=0, font=(FONT, SZ_INFO),
        )

    def _popup_free_menu(self, event):
        slug = self.selected_slug
        menu = self._menu()

        add = self._menu(menu)
        add.add_command(label="at the end", command=lambda: self._add_fallback(slug, None))
        add.add_command(label="at the top (new #1)", command=lambda: self._add_fallback(slug, 0))
        menu.add_cascade(label="Add as new fallback", menu=add)

        chain = self.fallback_entries
        replace = self._menu(menu)
        if chain:
            for index, entry in enumerate(chain):
                label = f"{index + 1} · {entry.get('model', '?')}  (via {entry.get('provider', '?')})"
                replace.add_command(
                    label=label, command=lambda i=index: self._replace_fallback(slug, i)
                )
        else:
            replace.add_command(label="no fallbacks configured", state="disabled")
        menu.add_cascade(label="Replace fallback", menu=replace)

        menu.add_separator()
        menu.add_command(label="Copy model name", command=self.copy_selected)
        menu.tk_popup(event.x_root, event.y_root)
        menu.grab_release()

    def _provider_for(self, slug):
        """Provider for a new fallback entry; OpenRouter rows will supply their own."""
        return "nous"

    def _add_fallback(self, slug, index):
        if self._fallback_busy:
            return
        try:
            chain = hermes_state.fallback_chain()
        except Exception as exc:  # noqa: BLE001
            self._fallback_failed(exc)
            return
        pos = len(chain) if index is None else max(0, min(index, len(chain)))
        chain.insert(pos, {"provider": self._provider_for(slug), "model": slug})
        self._write_fallbacks(chain, f"Added {slug} as fallback #{pos + 1}")

    def _replace_fallback(self, slug, index):
        if self._fallback_busy:
            return
        try:
            chain = hermes_state.fallback_chain()
        except Exception as exc:  # noqa: BLE001
            self._fallback_failed(exc)
            return
        if not 0 <= index < len(chain):
            self._flash_status("That fallback slot is gone — hit Refresh")
            return
        old = chain[index].get("model", "?")
        entry = dict(chain[index])
        entry["model"] = slug
        chain[index] = entry
        self._write_fallbacks(chain, f"Replaced fallback #{index + 1}: {old} → {slug}")

    def _write_fallbacks(self, chain, note):
        self._fallback_busy = True
        self._flash_status("Writing fallback chain…")

        def work():
            try:
                hermes_state.set_fallbacks(chain)
            except Exception as exc:  # noqa: BLE001
                self.after(0, lambda: self._fallback_failed(exc))
                return
            self.after(0, lambda: self._fallback_written(note))

        threading.Thread(target=work, daemon=True).start()

    def _fallback_written(self, note):
        self._fallback_busy = False
        self._flash_status(note)
        self._record_history("info", note)
        self._notify("Fallback chain", note, "ok")
        self.refresh_deep()

    def _fallback_failed(self, error):
        self._fallback_busy = False
        messagebox.showerror("Fallback update failed", str(error))
        self._flash_status("Fallback update failed")

    # ---------- config tab: drag to reorder, right-click to remove ----------

    def _on_cfg_hover(self, event):
        if self._drag_fb is not None:
            return
        item = self.tree2.identify_row(event.y)
        self.tree2.configure(cursor="fleur" if item in self._fb_chain else "")

    def _on_cfg_press(self, event):
        self._drag_fb = None
        if self._fallback_busy:
            return
        item = self.tree2.identify_row(event.y)
        if item is None or item not in self._fb_chain:
            return  # main and aux rows are not draggable
        self._drag_fb = {
            "item": item,
            "start_y": event.y,
            "active": False,
            "tags": tuple(self.tree2.item(item, "tags") or ()),
        }

    def _on_cfg_motion(self, event):
        drag = self._drag_fb
        if drag is None:
            return
        if not drag["active"]:
            if abs(event.y - drag["start_y"]) < 5:
                return
            drag["active"] = True
            self.tree2.configure(cursor="fleur")
            self.tree2.item(drag["item"], tags=("dragging",))
        target = self.tree2.identify_row(event.y)
        if target is None or target not in self._fb_chain or target == drag["item"]:
            return
        box = self.tree2.bbox(target)
        before = bool(box) and event.y < box[1] + box[3] / 2
        rel_target = self._fb_rows.index(target)
        rel_self = self._fb_rows.index(drag["item"])
        insert_at = rel_target if before else rel_target + 1
        if rel_self < insert_at:
            insert_at -= 1
        insert_at = max(0, min(insert_at, len(self._fb_rows) - 1))
        if insert_at == rel_self:
            return
        base = self.tree2.index(self._fb_rows[0])
        try:
            self.tree2.move(drag["item"], "", base + insert_at)
        except tk.TclError:
            self._cancel_drag()
            return
        self._fb_rows.insert(insert_at, self._fb_rows.pop(rel_self))

    def _on_cfg_release(self, event=None):
        drag = self._drag_fb
        self._drag_fb = None
        self.tree2.configure(cursor="")
        if drag is None:
            return
        try:
            self.tree2.item(drag["item"], tags=drag["tags"])
        except tk.TclError:
            pass
        if not drag["active"]:
            return
        order = [self._fb_chain[item] for item in self._fb_rows]
        if order == sorted(order):
            return
        try:
            chain = hermes_state.fallback_chain()
        except Exception as exc:  # noqa: BLE001
            self._fallback_failed(exc)
            return
        new_chain = [chain[i] for i in order]
        self._write_fallbacks(new_chain, "Reordered fallbacks")

    def _cancel_drag(self):
        drag = self._drag_fb
        self._drag_fb = None
        self.tree2.configure(cursor="")
        if drag is None:
            return
        try:
            self.tree2.item(drag["item"], tags=drag["tags"])
        except tk.TclError:
            pass

    def _on_cfg_rclick(self, event):
        item = self.tree2.identify_row(event.y)
        if item is None or item not in self._fb_chain:
            return  # main and aux rows get no menu
        index = self._fb_chain[item]
        self.tree2.selection_set(item)
        self.tree2.focus_set()
        self.selected_slug = self.tree2.item(item)["values"][1]
        menu = self._menu()
        menu.add_command(
            label=f"Remove fallback #{index + 1}",
            command=lambda: self._remove_fallback(index),
        )
        menu.add_separator()
        menu.add_command(label="Copy model name", command=lambda: self.copy_row(self.tree2))
        menu.tk_popup(event.x_root, event.y_root)
        menu.grab_release()

    def _remove_fallback(self, index):
        if self._fallback_busy:
            return
        try:
            chain = hermes_state.fallback_chain()
        except Exception as exc:  # noqa: BLE001
            self._fallback_failed(exc)
            return
        if not 0 <= index < len(chain):
            self._flash_status("That fallback slot is gone — hit Refresh")
            return
        removed = chain.pop(index)
        self._write_fallbacks(chain, f"Removed fallback #{index + 1}: {removed.get('model', '?')}")

    # ---------- timers ----------

    def _apply_timers(self):
        self.ui["auto_models"] = bool(self.auto_models_var.get())
        self.ui["deep"] = bool(self.deep_var.get())
        self.ui["bubbles"] = bool(self.bubbles_var.get())
        save_ui_state(self.ui)
        if self._models_after_id:
            self.after_cancel(self._models_after_id)
            self._models_after_id = None
        if self._deep_after_id:
            self.after_cancel(self._deep_after_id)
            self._deep_after_id = None
        if self.auto_models_var.get():
            self._models_after_id = self.after(MODELS_REFRESH_MS, self._models_tick)
        if self.deep_var.get():
            self._deep_after_id = self.after(DEEP_REFRESH_MS, self._deep_tick)

    def _models_tick(self):
        self.refresh_models()
        if self.auto_models_var.get():
            self._models_after_id = self.after(MODELS_REFRESH_MS, self._models_tick)

    def _deep_tick(self):
        self.refresh_deep()
        if self.deep_var.get():
            self._deep_after_id = self.after(DEEP_REFRESH_MS, self._deep_tick)


if __name__ == "__main__":
    try:
        App().mainloop()
    except KeyboardInterrupt:
        pass
