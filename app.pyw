#!/usr/bin/env python3w
"""Nous Free Models - tiny window that follows the installed Hermes skin."""
import datetime
import json
import os
import threading
import tkinter as tk
from tkinter import ttk

import hermes_state
import nous_core
import theme

FONT = "Segoe UI"
SZ_TITLE = 20
SZ_BODY = 13
SZ_TREE = 14
SZ_HEAD = 13

COLS = ("Model", "Context", "Inputs", "Price", "Flags", "Source")
WIDTHS = {"Model": 360, "Context": 110, "Inputs": 160, "Price": 100, "Flags": 210, "Source": 120}
CFG_COLS = ("Role", "Model", "Provider", "Status", "Notes")
CFG_WIDTHS = {"Role": 190, "Model": 340, "Provider": 90, "Status": 100, "Notes": 260}

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
        self.title("Nous Free Models")
        self.geometry("1180x700")
        self.minsize(960, 540)
        self.models = []
        self.cfg_rows = []
        self.usage_data = {"counts": {}, "fallbacks": [], "last": None}
        self.palette = dict(theme.FALLBACK_PALETTE)
        self.meta = {}
        self.choice = theme.load_choice()
        self.skins = ["Auto (follow Hermes)"] + theme.skin_names()
        self.ui = load_ui_state()
        self.last_models = "-"
        self.last_deep = "-"
        self._busy = False
        self._models_after_id = None
        self._deep_after_id = None
        self._poll_id = None
        self.combo_var = tk.StringVar()
        self.split_var = tk.BooleanVar(value=bool(self.ui.get("split")))
        self.auto_models_var = tk.BooleanVar(value=bool(self.ui.get("auto_models")))
        self.deep_var = tk.BooleanVar(value=bool(self.ui.get("deep")))

        palette, meta = theme.resolve(self.choice)
        self.palette, self.meta = palette, meta
        self.configure(bg=self.palette["bg"])
        self._style()
        self._build_ui()
        self._sync_combo()
        self.after(200, self.refresh)
        self._apply_timers()
        self._schedule_poll()

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
        style.configure("TCheckbutton", background=p["bg"], foreground=p["dim"], font=(FONT, SZ_BODY))
        style.map("TCheckbutton", background=[("active", p["bg"])])
        style.configure("Vertical.TScrollbar", background=p["head_bg"], troughcolor=p["bg"], borderwidth=0)
        style.configure(
            "TCombobox", fieldbackground=p["card"], background=p["head_bg"],
            foreground=p["fg"], arrowcolor=p["fg"],
        )
        style.map("TCombobox", fieldbackground=[("readonly", p["card"])], foreground=[("readonly", p["fg"])])
        style.configure("TNotebook", background=p["bg"], borderwidth=0)
        style.configure(
            "TNotebook.Tab", background=p["head_bg"], foreground=p["dim"],
            padding=(16, 8),
        )
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

    def _sync_combo(self):
        label = "Auto (follow Hermes)"
        if self.choice.get("mode") == "skin":
            label = self.choice.get("name", label)
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
        self.status.configure(
            text=f"Theme: {skin} ({'live' if source == 'engine' else source})",
            fg=self._c("dim"),
        )

    def _schedule_poll(self):
        if self._poll_id:
            self.after_cancel(self._poll_id)
        self._poll_id = self.after(POLL_MS, self._poll_tick)

    def _poll_tick(self):
        if self.choice.get("mode") == "auto":
            palette, meta = theme.resolve(self.choice)
            if palette != self.palette:
                self.apply_theme(palette, meta)
        self._schedule_poll()

    # ---------- ui ----------

    def _build_ui(self):
        for widget in self.winfo_children():
            widget.destroy()
        self._build_toolbar()
        if self.split_var.get():
            self._build_split()
        else:
            self._build_notebook()
        self._build_options()
        self._build_status()

    def _build_toolbar(self):
        p = self.palette
        bar = tk.Frame(self, bg=p["bg"])
        bar.pack(fill="x", padx=14, pady=(14, 4))

        tk.Label(bar, text="Nous Free Models", bg=p["bg"], fg=p["fg"],
                 font=("Segoe UI Semibold", SZ_TITLE)).pack(side="left")
        self.info = tk.Label(bar, text="", bg=p["bg"], fg=p["dim"], font=(FONT, SZ_BODY))
        self.info.pack(side="left", padx=(16, 0))

        combo = ttk.Combobox(
            bar, textvariable=self.combo_var, values=self.skins,
            state="readonly", width=24,
        )
        combo.bind("<<ComboboxSelected>>", self._on_skin_select)
        combo.pack(side="right", padx=(8, 0))

        ttk.Button(bar, text="About", command=self.show_about).pack(side="right", padx=8)
        ttk.Button(bar, text="Copy slug", command=self.copy_selected).pack(side="right", padx=8)
        ttk.Button(bar, text="Refresh", command=self.refresh).pack(side="right")

    def _build_notebook(self):
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=14, pady=(4, 2))
        tab_free = tk.Frame(self.nb, bg=self._c("bg"))
        tab_cfg = tk.Frame(self.nb, bg=self._c("bg"))
        self.nb.add(tab_free, text="Free models")
        self.nb.add(tab_cfg, text="In Hermes")
        self._build_catalog_tab(tab_free)
        self._build_config_tab(tab_cfg)

    def _build_split(self):
        self.pane = ttk.Panedwindow(self, orient="horizontal")
        self.pane.pack(fill="both", expand=True, padx=14, pady=(4, 2))
        left = tk.Frame(self.pane, bg=self._c("bg"))
        right = tk.Frame(self.pane, bg=self._c("bg"))
        self.pane.add(left, weight=3)
        self.pane.add(right, weight=2)
        self._build_catalog_tab(left)
        self._build_config_tab(right)

    def _build_options(self):
        row = tk.Frame(self, bg=self.palette["bg"])
        row.pack(fill="x", padx=16, pady=(2, 0))
        ttk.Checkbutton(
            row, text="Side by side", variable=self.split_var,
            command=self._toggle_split,
        ).pack(side="left")
        ttk.Checkbutton(
            row, text="Auto models (15 min)", variable=self.auto_models_var,
            command=self._apply_timers,
        ).pack(side="left", padx=(18, 0))
        ttk.Checkbutton(
            row, text="Deep check (4 h)", variable=self.deep_var,
            command=self._apply_timers,
        ).pack(side="left", padx=(18, 0))

    def _toggle_split(self):
        self.ui["split"] = bool(self.split_var.get())
        save_ui_state(self.ui)
        self._rebuild()

    def _build_catalog_tab(self, parent):
        wrap = tk.Frame(parent, bg=self._c("border"))
        wrap.pack(fill="both", expand=True, padx=0, pady=(2, 0))

        self.tree = ttk.Treeview(wrap, columns=COLS, show="headings", height=12)
        for col in COLS:
            self.tree.heading(col, text=col, anchor="w")
            self.tree.column(col, width=WIDTHS[col], anchor="w")
        self.tree.column("Model", minwidth=240, stretch=True)
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda _e: self.copy_selected())

        scroll = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scroll.set)

    def _build_config_tab(self, parent):
        p = self.palette
        wrap = tk.Frame(parent, bg=p["bg"])
        wrap.pack(fill="both", expand=True)

        self.usage = tk.Label(
            wrap, text="Recent API calls: ...", bg=p["bg"], fg=p["dim"],
            font=(FONT, SZ_BODY), anchor="w",
        )
        self.usage.pack(fill="x", padx=6, pady=(4, 2))

        inner = tk.Frame(wrap, bg=p["border"])
        inner.pack(fill="both", expand=True)

        self.tree2 = ttk.Treeview(inner, columns=CFG_COLS, show="headings", height=10)
        for col in CFG_COLS:
            self.tree2.heading(col, text=col, anchor="w")
            self.tree2.column(col, width=CFG_WIDTHS[col], anchor="w")
        self.tree2.column("Notes", minwidth=180, stretch=True)
        self.tree2.pack(side="left", fill="both", expand=True)
        self.tree2.bind("<Double-1>", lambda _e: self.copy_row(self.tree2))

        self.tree2.tag_configure("free", foreground=p["ok"])
        self.tree2.tag_configure("paid", foreground=p["warn"])
        self.tree2.tag_configure("missing", foreground=p["error"])

        scroll = ttk.Scrollbar(inner, orient="vertical", command=self.tree2.yview)
        scroll.pack(side="right", fill="y")
        self.tree2.configure(yscrollcommand=scroll.set)

    def _build_status(self):
        self.status = tk.Label(
            self, text="Checking...", bg=self._c("bg"), fg=self._c("dim"),
            font=(FONT, SZ_BODY), anchor="w",
        )
        self.status.pack(fill="x", padx=16, pady=(2, 12))

    def show_about(self):
        p = self.palette
        win = tk.Toplevel(self)
        win.title("About Nous Free Models")
        win.configure(bg=p["bg"])
        win.geometry("460x300")
        win.transient(self)
        win.grab_set()

        tk.Label(win, text="Nous Free Models", bg=p["bg"], fg=p["fg"],
                 font=("Segoe UI Semibold", 18)).pack(pady=(18, 4))
        lines = [
            "Live free-model catalog plus a Hermes config check.",
            "",
            "Built with AI assistance — Hermes Agent.",
            "Data: Nous Portal & inference APIs (live), local Hermes config.",
            "License: MIT (see LICENSE) · NOTICE.md",
        ]
        for line in lines:
            tk.Label(win, text=line, bg=p["bg"], fg=p["dim"],
                     font=(FONT, 12), justify="left").pack(fill="x", padx=24)
        ttk.Button(win, text="Close", command=win.destroy).pack(pady=16)

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
            self.after(0, lambda: self._show(models_out, meta_out, cfg_rows, usage))

        threading.Thread(target=work, daemon=True).start()

    def _classify(self, slug, free_names, catalog_ids):
        if slug in free_names:
            return "free", "in live free list"
        base = slug.split(":", 1)[0]
        if slug in catalog_ids or base in catalog_ids:
            return "paid", "listed, not free"
        return "missing", "not in catalog (dead?)"

    def _insert(self, model):
        flags = []
        if model["vision"]:
            flags.append("vision")
        if model["video"]:
            flags.append("video")
        if model["compaction"]:
            flags.append("compaction")
        ctx = model["context"]
        self.tree.insert(
            "", "end",
            values=(
                model["name"],
                f"{ctx:,}" if ctx else "?",
                model["inputs"],
                "$0.00 / 1M",
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
        catalog_ids = set(self.meta.get("catalog_ids", []))
        for row in rows:
            status, detail = self._classify(row["model"], free_names, catalog_ids)
            self.tree2.insert(
                "", "end",
                values=(
                    row["role"], row["model"], row["provider"],
                    status.upper(), detail,
                ),
                tags=(status,),
            )

        counts = usage.get("counts", {})
        top = ", ".join(f"{k} ×{v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1])[:4])
        text = f"Recent API calls: {top or 'none'}"
        if usage.get("last"):
            text += f" · last: {usage['last']}"
        fallbacks = usage.get("fallbacks") or []
        if fallbacks:
            text += f" · fallbacks fired: {len(fallbacks)}"
        self.usage.configure(text=text)

    def _status_line(self):
        free = ""
        if self.meta:
            free = f" · {self.meta.get('free_count')} free of {self.meta.get('catalog_rows')}"
        return f"Models {self.last_models} · Config {self.last_deep}{free}"

    def _show(self, models, meta, cfg_rows, usage):
        self._busy = False
        stamp = datetime.datetime.now().strftime("%H:%M")
        if models is not None:
            self.models = models
            self.meta = meta
            if hasattr(self, "tree"):
                self.tree.delete(*self.tree.get_children())
                for model in models:
                    self._insert(model)
            self.last_models = stamp
        if usage is not None:
            self._render_config(cfg_rows, usage)
            self.last_deep = stamp
        self.status.configure(text=self._status_line(), fg=self._c("ok"))
        self.info.configure(text="account: free tier")

    def _show_error(self, error):
        self._busy = False
        self.status.configure(text=f"Error: {error}", fg=self._c("error"))
        self.info.configure(text="")

    def copy_row(self, tree):
        sel = tree.selection()
        if not sel:
            return
        values = tree.item(sel[0])["values"]
        slug = values[0] if tree is self.tree else values[1]
        self.clipboard_clear()
        self.clipboard_append(slug)
        self.status.configure(text=f"Copied: {slug}", fg=self._c("accent"))

    def copy_selected(self):
        if hasattr(self, "tree"):
            self.copy_row(self.tree)

    # ---------- timers ----------

    def _apply_timers(self):
        self.ui["auto_models"] = bool(self.auto_models_var.get())
        self.ui["deep"] = bool(self.deep_var.get())
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