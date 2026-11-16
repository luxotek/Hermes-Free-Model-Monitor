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
SZ_TREE = 14
SZ_HEAD = 13

COLS = ("Model", "Context", "Inputs", "Output", "Released", "Flags", "Source")
WIDTHS = {"Model": 360, "Context": 110, "Inputs": 160, "Output": 110,
          "Released": 110, "Flags": 200, "Source": 120}
CFG_COLS = ("Role", "Model", "Status", "Last error", "Calls")
CFG_WIDTHS = {"Role": 130, "Model": 250, "Status": 250, "Last error": 300, "Calls": 50}
# Per-column ceilings for the content-sized fit: the error cell carries a date,
# a label and a retry delay, so it needs room the free tab's columns do not.
CFG_CAPS = {"Role": 200, "Model": 380, "Status": 340, "Last error": 420, "Calls": 90}

SZ_INFO = 14
SZ_POPUP = 14        # Additional info popup body
SZ_POPUP_META = 13   # Additional info popup meta lines

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


def _plain(text):
    """Undo the newlines the config table wraps its cells with."""
    return str(text).replace("\n", " ")


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
        self.trouble_data = {}
        self.limits_data = {}
        self._scroll_sync_after_id = None
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
        self._cfg_style = style
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
        # The config table carries its own style so its single-line rows and
        # tag colours never leak into the free tab's Treeview.
        style.configure(
            "Cfg.Treeview", background=p["card"], foreground=p["fg"],
            fieldbackground=p["card"], borderwidth=0, rowheight=38,
            font=(FONT, SZ_TREE),
        )
        style.configure(
            "Cfg.Treeview.Heading", background=p["head_bg"], foreground=p["head_fg"],
            relief="flat", font=("Segoe UI Semibold", SZ_HEAD), padding=(8, 6),
        )
        style.map(
            "Cfg.Treeview",
            background=[("selected", p["selection"])],
            foreground=[("selected", p["fg"])],
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
        self._render_config(self.cfg_rows, self.usage_data,
                            self.trouble_data, self.limits_data)
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
        # Footer BEFORE the notebook. The packer serves slaves in pack order, so
        # packing the notebook first let its `expand` request take the whole
        # window and push these lines off the bottom edge (the Additional info
        # button ended up at y=0, unmapped, on any window under ~700 px).
        self._build_status()
        self._build_usage_bar()
        self._build_limits_bar()
        self._build_info_bar()
        self._build_notebook()

    def _build_toolbar(self):
        p = self.palette
        bar = tk.Frame(self, bg=p["bg"])
        bar.pack(fill="x", padx=14, pady=(14, 4))
        # The title is the only stretchable column, so a narrow window clips it
        # rather than pushing the buttons off the bar; row 1 (the info line)
        # spans all five columns.
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

    def _build_info_bar(self):
        p = self.palette
        bar = tk.Frame(self, bg=p["bg"])
        bar.pack(side="bottom", fill="x", padx=14, pady=(2, 0))
        self.info_btn = ttk.Button(bar, text="Additional info",
                                   command=self.open_model_info)
        # Left side: the popup is right-justified to the window edge, so a
        # right-packed button sat underneath it.
        self.info_btn.pack(side="left")
        self.info_btn.state(["disabled"])

    def _build_usage_bar(self):
        # Bottom of the window, outside the tab panel: recent per-model API call
        # counts from logs/agent.log.
        self.usage = tk.Label(
            self, text="Recent API calls: ...", bg=self._c("bg"), fg=self._c("dim"),
            font=(FONT, SZ_INFO), anchor="w",
        )
        self.usage.pack(side="bottom", fill="x", padx=16, pady=(2, 4))

    def _build_limits_bar(self):
        # The account's live ceilings, also below the panel so they read as
        # window-level facts rather than belonging to one tab.
        self.limits = tk.Label(
            self, text="Free-tier limits unknown — hit Refresh",
            bg=self._c("bg"), fg=self._c("accent"), font=(FONT, SZ_INFO), anchor="w",
        )
        self.limits.pack(side="bottom", fill="x", padx=16, pady=(2, 0))

    def _build_catalog_tab(self, parent):
        wrap = tk.Frame(parent, bg=self._c("bg"))
        wrap.pack(fill="both", expand=True, padx=0, pady=(2, 0))

        self.tree = ttk.Treeview(wrap, columns=COLS, show="headings", height=12)
        for col in COLS:
            self.tree.heading(col, text=col, anchor="w")
            self.tree.column(col, width=WIDTHS[col], anchor="w")
        # Scrollbars pack before the tree: the packer serves slaves in order, so
        # a tree packed first with `expand` takes the whole panel and leaves the
        # scrollbars with no strip to occupy.
        self.tree_vscroll = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree_vscroll.pack(side="right", fill="y")
        self.tree_hscroll = ttk.Scrollbar(wrap, orient="horizontal", command=self.tree.xview)
        self.tree_hscroll.pack(side="bottom", fill="x")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda _e: self.copy_selected())
        self.tree.bind("<Button-3>", self._on_free_rclick)
        self.tree.configure(yscrollcommand=self.tree_vscroll.set, xscrollcommand=self.tree_hscroll.set)
        self.tree.bind("<Configure>", self._on_tree_configure, add="+")

    def _build_config_tab(self, parent):
        p = self.palette
        wrap = tk.Frame(parent, bg=p["bg"])
        wrap.pack(fill="both", expand=True)

        inner = tk.Frame(wrap, bg=p["bg"])
        inner.pack(fill="both", expand=True)

        self.tree2 = ttk.Treeview(inner, columns=CFG_COLS, show="headings",
                                  height=10, style="Cfg.Treeview")
        for col in CFG_COLS:
            self.tree2.heading(col, text=col, anchor="w")
            self.tree2.column(col, width=CFG_WIDTHS[col], anchor="w")
        # Scrollbars before the tree, for the same pack-order reason as the
        # free tab.
        self.tree2_vscroll = ttk.Scrollbar(inner, orient="vertical", command=self.tree2.yview)
        self.tree2_vscroll.pack(side="right", fill="y")
        self.tree2_hscroll = ttk.Scrollbar(inner, orient="horizontal", command=self.tree2.xview)
        self.tree2_hscroll.pack(side="bottom", fill="x")
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
        # A preview/alpha/beta slot is amber across the row: ttk colours a whole
        # item, not one cell, and the status stays readable as text.
        self.tree2.tag_configure("temp", foreground=p["warn"])
        self.tree2.tag_configure("dragging", background=p["accent"], foreground=p["fg"])

        self.tree2_vscroll = ttk.Scrollbar(inner, orient="vertical", command=self.tree2.yview)
        self.tree2_vscroll.pack(side="right", fill="y")
        self.tree2_hscroll = ttk.Scrollbar(inner, orient="horizontal", command=self.tree2.xview)
        self.tree2_hscroll.pack(side="bottom", fill="x")
        self.tree2.configure(yscrollcommand=self.tree2_vscroll.set, xscrollcommand=self.tree2_hscroll.set)
        self.tree2.bind("<Configure>", self._on_tree_configure, add="+")

    def _build_status(self):
        self.status = tk.Label(
            self, text="Connecting…", bg=self._c("bg"), fg=self._c("dim"),
            font=(FONT, SZ_INFO), anchor="w",
        )
        self.status.pack(side="bottom", fill="x", padx=16, pady=(14, 12))

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
        # Also drop the colour a flash set, or a green "copied" line sticks.
        self.status.configure(text="   ·   ".join(parts) or "Connecting…",
                              fg=self._c("dim"))

    def _flash_status(self, message, ms=2600):
        if not hasattr(self, "status"):
            return
        self.status.configure(text=message, fg=self._c("ok"))
        if getattr(self, "_flash_after_id", None):
            self.after_cancel(self._flash_after_id)
        self._flash_after_id = self.after(ms, self._refresh_status)

    # ---------- settings / about ----------

    def _close_popups(self):
        """Only one popup at a time: drop any sheet already open."""
        for attr in ("_info_win", "_settings_win"):
            win = getattr(self, attr, None)
            if win is not None:
                try:
                    if win.winfo_exists():
                        win.destroy()
                except Exception:  # noqa: BLE001
                    pass
                setattr(self, attr, None)

    def open_settings(self):
        self._close_popups()
        p = self.palette
        win = tk.Toplevel(self)
        self._settings_win = win
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

    def _selected_model(self):
        """(title, info, [(label, value), ...]) for the active tab's selected row."""
        on_free = self.nb.index(self.nb.select()) == 0
        tree = self.tree if on_free else self.tree2
        sel = tree.selection()
        if not sel:
            return None
        values = tree.item(sel[0])["values"]
        if on_free:
            info = next((m for m in self.models if m["name"] == values[0]), None) or {}
            facts = [("Context", values[1]), ("Inputs", values[2]),
                     ("Output", values[3]), ("Released", values[4]),
                     ("Flags", values[5]), ("Source", values[6])]
            return values[0], info, facts
        facts = [("Role", _plain(values[0])), ("Status", _plain(values[2])),
                 ("Last error", _plain(values[3])), ("Calls", _plain(values[4]))]
        return _plain(values[1]), self._model_info(_plain(values[1])), facts

    @staticmethod
    def _source_url(info):
        """Where the model actually lives: HuggingFace, OpenRouter or Nous."""
        extra = (info or {}).get("extra") or {}
        if extra.get("hf"):
            return f"https://huggingface.co/{extra['hf']}", "HuggingFace"
        if extra.get("or_slug"):
            return f"https://openrouter.ai/{extra['or_slug']}", "OpenRouter"
        return "https://portal.nousresearch.com/models", "Nous Portal"

    def _popup_sections(self, on_free, slug, info, facts):
        """[(label, value, palette key)] for the popup's labelled sections.

        The config tab keeps only the verdict and the error on the table, so
        everything it dropped lands here — lifecycle, failover, provider.
        """
        fact_map = dict(facts)
        if on_free:
            return [
                ("Context", fact_map.get("Context", "-"), "fg"),
                ("Inputs", fact_map.get("Inputs", "-"), "fg"),
                ("Output", fact_map.get("Output", "-"), "fg"),
                ("Released", fact_map.get("Released", "-"), "fg"),
                ("Source", fact_map.get("Source", "-"), "fg"),
            ]
        status = fact_map.get("Status", "")
        temp = self._temp_text(info)
        row = next((m for m in self.models if m.get("name") == slug), None)
        src = row or info or {}
        route = src.get("route") or (info or {}).get("route")
        return [
            ("Verdict", status or "None",
             "ok" if "FREE" in status else "warn" if "PAID" in status else "error"),
            ("Lifecycle", temp if temp != "-" else "None",
             "warn" if info.get("temp") else "fg"),
            ("Failover", self._fallback_text(slug, self.trouble_data), "accent"),
            ("Recent calls", fact_map.get("Calls", "None"), "fg"),
            ("Source", src.get("source") or "None", "fg"),
            ("Provider", hermes_state.provider_for_route(route) or "None", "fg"),
        ]

    def _section_grid(self, parent, sections, width):
        """Label-above-value sections in three columns, like the mockup."""
        per_row = 3
        cell_w = max((width - 44 - 2 * 14) // per_row, 120)
        p = self.palette
        grid = tk.Frame(parent, bg=p["bg"])
        grid.pack(fill="x", pady=(10, 0))
        for col in range(per_row):
            grid.columnconfigure(col, weight=1, uniform="sec")
        for index, (label, value, color_key) in enumerate(sections):
            row, col = divmod(index, per_row)
            cell = tk.Frame(grid, bg=p["bg"])
            cell.grid(row=row, column=col, sticky="nw", padx=(0, 14), pady=(0, 8))
            tk.Label(cell, text=label.upper(), bg=p["bg"], fg=p["dim"],
                     font=("Segoe UI Semibold", SZ_POPUP_META - 2),
                     anchor="w").pack(anchor="w")
            tk.Label(cell, text=value, bg=p["bg"], fg=p[color_key],
                     font=(FONT, SZ_POPUP - 1), anchor="w", justify="left",
                     wraplength=cell_w).pack(anchor="w")

    def open_model_info(self):
        """Popup sheet for the selected row — everything the panel used to squeeze in."""
        self._close_popups()
        p = self.palette
        picked = self._selected_model()
        if picked is None:
            return
        title, info, facts = picked
        on_free = self.nb.index(self.nb.select()) == 0
        chips, body, scores = self._model_detail(info, lifecycle=on_free)

        win = tk.Toplevel(self)
        win.title(f"Additional info — {title}")
        win.configure(bg=p["bg"])
        win.resizable(False, False)
        win.transient(self)
        self._info_win = win

        width = max(min(self.winfo_width() - 48, 760), 520)
        wrap = width - 44

        head = tk.Frame(win, bg=p["bg"])
        head.pack(fill="x", padx=22, pady=(16, 4))
        tk.Label(head, text=f"Additional info — {title}", bg=p["bg"], fg=p["fg"],
                 font=("Segoe UI Semibold", SZ_POPUP + 1), anchor="w", justify="left",
                 wraplength=wrap).pack(fill="x")
        self._section_grid(head, self._popup_sections(on_free, title, info, facts), width)
        tk.Label(head, text=chips, bg=p["bg"], fg=p["accent"], font=(FONT, SZ_POPUP_META),
                 anchor="w", justify="left", wraplength=wrap).pack(fill="x", pady=(2, 0))
        url, host = self._source_url(info)
        link = tk.Label(head, text=f"Full description on {host} →",
                        bg=p["bg"], fg=p["accent"], cursor="hand2", anchor="w",
                        font=("Segoe UI Semibold", SZ_POPUP_META, "underline"),
                        justify="left", wraplength=wrap)
        link.pack(fill="x", pady=(4, 0))
        link.bind("<Button-1>", lambda _e, u=url: webbrowser.open(u))

        # Close packs BEFORE the scrollable body. The packer serves slaves in
        # order, so a button packed after an `expand` slave is served last: once
        # the window is shorter than its content it gets squeezed to zero, which
        # is exactly how the button disappeared.
        foot = tk.Frame(win, bg=p["bg"])
        foot.pack(side="bottom", fill="x", padx=22, pady=(8, 14))
        close_btn = ttk.Button(foot, text="Close", command=win.destroy)
        close_btn.pack(side="right")

        box = tk.Frame(win, bg=p["border"])
        box.pack(fill="both", expand=True, padx=22)
        inner = tk.Frame(box, bg=p["card"])
        inner.pack(fill="both", expand=True)
        text = tk.Text(inner, height=12, bg=p["card"], fg=p["fg"], font=(FONT, SZ_POPUP),
                       relief="flat", wrap="word", padx=10, pady=8)
        text.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(inner, orient="vertical", command=text.yview)
        sb.pack(side="right", fill="y")
        text.configure(yscrollcommand=sb.set)
        text.insert("end", body + "\n")
        if scores:
            text.insert("end", "\n" + scores + "\n")
        text.configure(state="disabled")

        win.bind("<Escape>", lambda _e: win.destroy())
        win.bind("<Destroy>", lambda _e: setattr(self, "_info_win", None))

        win.update_idletasks()
        screen_cap = self.winfo_screenheight() - 100
        width = min(width, self.winfo_screenwidth() - 20)
        # Size to the content, but never so short that the header squeezes the
        # description into unreadability (it scrolls instead), and never taller
        # than the screen. The window is fixed-size, so this is the whole
        # contract: everything below the header lives in the scrolling area.
        # Fixed-size window: size it to the content, capped so the header plus a
        # readable slice of description plus Close fit — the rest scrolls.
        height = min(max(win.winfo_reqheight(), head.winfo_reqheight() + 200),
                     head.winfo_reqheight() + 260, screen_cap)
        x = self.winfo_rootx() + self.winfo_width() - width
        y = self.winfo_rooty() + max((self.winfo_height() - height) // 2, 0)
        y = max(min(y, self.winfo_screenheight() - height - 8), 8)
        win.geometry(f"{width}x{height}+{x}+{y}")

    def _open_doc(self, filename):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
        try:
            os.startfile(path)
        except Exception:
            webbrowser.open("https://github.com/luxotek/Hermes-Free-Model-Monitor")

    # ---------- column fitting ----------

    def _autofit_columns(self, tree, hscroll, vscroll=None, caps=None):
        """Size each column to its own widest cell; scroll rather than wrap."""
        font = self._measure_font
        for index, col in enumerate(tree["columns"]):
            width = font.measure(str(tree.heading(col)["text"])) + 24
            for item in tree.get_children():
                values = tree.item(item)["values"]
                if index < len(values):
                    width = max(width, font.measure(str(values[index])) + 24)
            cap = (caps or {}).get(col, 460 if col == "Model" else 300)
            tree.column(col, width=min(max(width, 64), cap), stretch=False)
        tree.update_idletasks()
        self._sync_hscroll(tree, hscroll)
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
            vscroll.pack(side="right", fill="y", before=tree)
        else:
            vscroll.pack_forget()

    def _on_tree_configure(self, event):
        """Scrollbars follow the panel; re-checked once layout has settled."""
        if event.widget is self.tree2:
            self._sync_vscroll(self.tree2, self.tree2_vscroll)
            self._sync_hscroll(self.tree2, self.tree2_hscroll)
        else:
            self._sync_vscroll(self.tree, self.tree_vscroll)
            self._sync_hscroll(self.tree, self.tree_hscroll)
        self._schedule_scroll_sync()

    def _schedule_scroll_sync(self):
        """Re-run the scrollbar check after the resize has settled.

        `<Configure>` can arrive while the tree still reports its previous
        width, which leaves the horizontal scrollbar showing the old answer.
        """
        if self._scroll_sync_after_id:
            self.after_cancel(self._scroll_sync_after_id)
        self._scroll_sync_after_id = self.after(120, self._scroll_sync)

    def _scroll_sync(self):
        self._scroll_sync_after_id = None
        try:
            for tree, hs, vs in ((self.tree, self.tree_hscroll, self.tree_vscroll),
                                 (self.tree2, self.tree2_hscroll, self.tree2_vscroll)):
                self._sync_vscroll(tree, vs)
                self._sync_hscroll(tree, hs)
        except tk.TclError:
            pass

    def _sync_hscroll(self, tree, hscroll):
        """Show the horizontal scrollbar only when the columns overflow."""
        if tree is None or hscroll is None:
            return
        try:
            if not tree.winfo_exists():
                return
        except Exception:
            return
        viewport = tree.winfo_width() - 4
        if viewport <= 1:
            return  # not laid out yet; <Configure> re-syncs
        need = sum(tree.column(col, "width") for col in tree["columns"]) > viewport
        if need == bool(hscroll.winfo_ismapped()):
            return
        if need:
            # `before` keeps the scrollbar ahead of the tree in pack order; when
            # the tree is served first its `expand` takes the whole panel and
            # the re-packed scrollbar gets no strip at all.
            hscroll.pack(side="bottom", fill="x", before=tree)
        else:
            hscroll.pack_forget()

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
            trouble = {}
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
                try:
                    trouble = hermes_state.troubleshooting()
                except Exception:
                    trouble = {}
            # Paint first, then spend the slow network calls on the limits line.
            # The rate-limit probe is a live completion (~4 s) and the
            # OpenRouter pool another request; neither should hold the panels.
            self.after(0, lambda: self._show(
                models_out, meta_out, cfg_rows, usage, fb_entries, trouble))
            if deep:
                try:
                    limits = self._probe_limits(cfg_rows)
                except Exception:
                    limits = {}
                self.after(0, lambda: self._render_limits(limits))

        threading.Thread(target=work, daemon=True).start()

    def _probe_limits(self, cfg_rows):
        """The account's live ceilings: a probe for the Nous bucket, plus the
        OpenRouter pool. One tiny completion; a 429 still answers."""
        limits = {}
        main = next((r["model"] for r in cfg_rows if r["role"].startswith("main")), None)
        if main:
            try:
                limits["probe"] = hermes_state.probe_rate_limit(main)
            except Exception as exc:  # noqa: BLE001
                limits["probe"] = {"error": str(exc)}
        try:
            limits["openrouter"] = nous_core.openrouter_pool()
        except Exception:
            limits["openrouter"] = None
        return limits

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
    def _temp_text(info):
        """Lifecycle column: the marker is the alarm, so it leads."""
        temp = info.get("temp") or ""
        end = info.get("end") or ""
        if temp and end:
            return f"{temp.upper()} · ends {end}"
        if temp:
            return temp.upper()
        if end:
            return f"ends {end}"
        return "-"

    @staticmethod
    def _stamp_text(stamp):
        """`2026-11-16 18:24:38` -> `11/16/2026 18:24`; '' when unreadable.

        The time of day is part of the stamp on purpose: a `retry 3h36m` delay
        is meaningless without knowing when it started.
        """
        match = re.match(r"^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})", str(stamp or ""))
        if not match:
            return ""
        return (f"{match.group(2)}/{match.group(3)}/{match.group(1)} "
                f"{match.group(4)}:{match.group(5)}")

    @staticmethod
    def _last_error_text(slug, trouble):
        """`11/16/2026 18:24 · 429 rate limit ×43 · retry 2s`, or `No error`.

        When first, then what, then the delay: the timestamp is what makes a
        bare `404 gone ×3` mean something, and the time of day is what makes
        the retry delay interpretable.
        """
        rec = (trouble or {}).get("errors", {}).get(slug)
        if not rec:
            return "No error"
        stamp = App._stamp_text(rec.get("last"))
        text = f"{rec.get('label', 'error')} ×{rec.get('count', 1)}"
        if rec.get("label", "").startswith("429"):
            asked = (trouble or {}).get("retry", {}).get(slug)
            wait = hermes_state._duration(asked)
            if wait:
                text += f" · retry {wait}"
        return f"{stamp} · {text}" if stamp else text

    @staticmethod
    def _fallback_text(slug, trouble):
        """`→ stepfun/step-3.7-flash:free ×3` (failed over to) / `← …` (caught one)."""
        rec = (trouble or {}).get("fallbacks", {}).get(slug)
        if not rec:
            return "None"
        return f"{rec['dir']} {rec['other']} ×{rec['count']}"

    @staticmethod
    def _calls_text(slug, trouble):
        return str((trouble or {}).get("calls", {}).get(slug, 0))

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

    def _render_config(self, rows, usage, trouble=None, limits=None):
        trouble = trouble or {}
        self.cfg_rows = rows
        self.usage_data = usage
        self.trouble_data = trouble
        self.limits_data = limits or {}
        if not hasattr(self, "tree2"):
            return
        self.tree2.delete(*self.tree2.get_children())
        free_names = {m["name"] for m in self.models}
        catalog_ids = set(self.catalog_meta.get("catalog_ids", []))
        for row in rows:
            status, detail = self._classify(row["model"], free_names, catalog_ids)
            info = self._model_info(row["model"])
            slug = row["model"]
            tags = [status]
            if info.get("temp"):
                tags.append("temp")
            values = (
                row["role"], slug, f"{status.upper()} · {detail}",
                self._last_error_text(slug, trouble),
                self._calls_text(slug, trouble),
            )
            self.tree2.insert("", "end", values=values, tags=tuple(tags))

        # Fallback rows only: remember which tree row is which fallback_providers slot
        # so they can be dragged into a new order and removed by right-click.
        self._fb_rows = []
        self._fb_chain = {}
        for item in self.tree2.get_children():
            role = _plain(self.tree2.item(item)["values"][0])
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

        self._render_limits(limits)

        if rows:
            self._clear_empty("config")
        elif getattr(self, "_data_loaded", False) and hasattr(self, "tree2"):
            self._empty_overlay(
                "config", self.tree2.master,
                "No configured models found",
                ["Nothing returned for model.default, auxiliary pins, or fallbacks.",
                 "Tip: anything pinned here is classified FREE / PAID / MISSING."],
            )
        self._autofit_columns(self.tree2, self.tree2_hscroll, self.tree2_vscroll,
                              caps=CFG_CAPS)

    def _render_limits(self, limits):
        """The account's live ceilings: Nous fair-share bucket + OpenRouter pool."""
        if not hasattr(self, "limits") or limits is None:
            return  # not fetched yet on this pass; keep the previous reading
        parts = []
        probe = (limits or {}).get("probe") or {}
        if probe.get("remaining") is not None and probe.get("limit"):
            reset = probe.get("reset")
            tail = f" · resets in {hermes_state._duration(reset)}" if reset else ""
            parts.append(
                f"Nous free tier: {probe['remaining']}/{probe['limit']} requests{tail}"
            )
        pool = (limits or {}).get("openrouter")
        if pool and pool.get("limit"):
            parts.append(
                f"OpenRouter free pool: {pool.get('remaining')}/{pool['limit']} today"
            )
        self.limits.configure(text="   ·   ".join(parts) or "Free-tier limits unknown — hit Refresh")

    def _show(self, models, meta, cfg_rows, usage, fb_entries=None, trouble=None, limits=None):
        self._busy = False
        if fb_entries is not None:
            self.fallback_entries = fb_entries
        stamp = datetime.datetime.now().strftime("%H:%M")
        if models is not None:
            self.models = models
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
            self._render_config(cfg_rows, usage, trouble, limits)
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
        self.selected_slug = values[0] if tree is self.tree else _plain(values[1]).replace(" ", "")
        if self.set_main_btn is not None:
            self.set_main_btn.state(["!disabled"])
        if getattr(self, "info_btn", None) is not None:
            self.info_btn.state(["!disabled"])

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

    def _copy(self, text):
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update()
        self._flash_status("Copied: " + text)

    def copy_selected(self):
        if not self.tree.selection():
            return
        self._copy(self.tree.item(self.tree.selection()[0])["values"][0])

    def copy_row(self, tree):
        if not tree.selection():
            return
        self._copy(_plain(tree.item(tree.selection()[0])["values"][1]))

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
        menu.add_command(label="Additional info", command=self.open_model_info)
        menu.tk_popup(event.x_root, event.y_root)
        menu.grab_release()

    def _provider_for(self, slug):
        """Provider for a new fallback, read off the model's own API route.

        The portal reports `source` per model and the OpenRouter models endpoint
        is OpenRouter by definition, so this is data rather than an assumption
        that everything is Nous.
        """
        row = next((m for m in self.models if m.get("name") == slug), None)
        provider = hermes_state.provider_for_route((row or {}).get("route"))
        if provider is None:
            self._flash_status(f"Cannot tell which provider serves {slug} — hit Refresh")
        return provider

    def _fallback_entry(self, slug, base=None):
        """A chain entry for `slug`, routed by the model's own API source.

        `base` carries over a slot's extra keys when replacing; provider and
        model always come from the route the API reported.
        """
        provider = self._provider_for(slug)
        if provider is None:
            return None
        entry = dict(base or {})
        entry["provider"] = provider
        entry["model"] = slug
        return entry

    def _add_fallback(self, slug, index):
        if self._fallback_busy:
            return
        try:
            chain = hermes_state.fallback_chain()
        except Exception as exc:  # noqa: BLE001
            self._fallback_failed(exc)
            return
        entry = self._fallback_entry(slug)
        if entry is None:
            return
        pos = len(chain) if index is None else max(0, min(index, len(chain)))
        chain.insert(pos, entry)
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
        entry = self._fallback_entry(slug, chain[index])
        if entry is None:
            return
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
        drag = self._end_drag()
        if drag is None or not drag["active"]:
            return
        try:
            chain = hermes_state.fallback_chain()
        except Exception as exc:  # noqa: BLE001
            self._fallback_failed(exc)
            return
        order = [self._fb_chain[item] for item in self._fb_rows]
        if order == sorted(order):
            return
        self._write_fallbacks([chain[i] for i in order], "Reordered fallbacks")

    def _end_drag(self):
        """Clear the drag state and put the row's cursor and tags back."""
        drag = self._drag_fb
        self._drag_fb = None
        self.tree2.configure(cursor="")
        if drag is None:
            return None
        try:
            self.tree2.item(drag["item"], tags=drag["tags"])
        except tk.TclError:
            pass
        return drag

    def _cancel_drag(self):
        self._end_drag()

    def _on_cfg_rclick(self, event):
        item = self.tree2.identify_row(event.y)
        if item is None or item not in self._fb_chain:
            return  # main and aux rows get no menu
        index = self._fb_chain[item]
        self.tree2.selection_set(item)
        self.tree2.focus_set()
        self.selected_slug = _plain(self.tree2.item(item)["values"][1]).replace(" ", "")
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
