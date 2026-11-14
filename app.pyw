#!/usr/bin/env python3w
"""Nous Free Models - tiny window that follows the installed Hermes skin."""
import datetime
import threading
import tkinter as tk
from tkinter import ttk

import hermes_state
import nous_core
import theme

COLS = ("Model", "Context", "Inputs", "Price", "Flags", "Source")
WIDTHS = {"Model": 320, "Context": 95, "Inputs": 140, "Price": 90, "Flags": 190, "Source": 110}
CFG_COLS = ("Role", "Model", "Provider", "Status", "Notes")
CFG_WIDTHS = {"Role": 170, "Model": 300, "Provider": 80, "Status": 90, "Notes": 230}
REFRESH_MS = 15 * 60 * 1000
POLL_MS = 3000


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Nous Free Models")
        self.geometry("1000x560")
        self.minsize(820, 420)
        self.models = []
        self.cfg_rows = []
        self.usage_data = {"counts": {}, "fallbacks": [], "last": None}
        self.palette = dict(theme.FALLBACK_PALETTE)
        self.meta = {}
        self.choice = theme.load_choice()
        self.skins = ["Auto (follow Hermes)"] + theme.skin_names()
        self._busy = False
        self._after_id = None
        self._poll_id = None
        self.combo_var = tk.StringVar()

        palette, meta = theme.resolve(self.choice)
        self.palette, self.meta = palette, meta
        self.configure(bg=self.palette["bg"])
        self._style()
        self._build_ui()
        self._sync_combo()
        self.after(200, self.refresh)
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
            fieldbackground=p["card"], borderwidth=0, rowheight=26,
            font=("Segoe UI", 10),
        )
        style.configure(
            "Treeview.Heading", background=p["head_bg"], foreground=p["head_fg"],
            relief="flat", font=("Segoe UI Semibold", 9), padding=(6, 4),
        )
        style.map(
            "Treeview",
            background=[("selected", p["selection"])],
            foreground=[("selected", p["fg"])],
        )
        style.configure("TButton", background=p["head_bg"], foreground=p["fg"], borderwidth=0, padding=6)
        style.map("TButton", background=[("active", p["border"])])
        style.configure("TCheckbutton", background=p["bg"], foreground=p["dim"], font=("Segoe UI", 9))
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
            padding=(12, 5),
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
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=12, pady=(4, 6))
        tab_free = tk.Frame(self.nb, bg=self._c("bg"))
        tab_cfg = tk.Frame(self.nb, bg=self._c("bg"))
        self.nb.add(tab_free, text="Free models")
        self.nb.add(tab_cfg, text="In Hermes")
        self._build_catalog_tab(tab_free)
        self._build_config_tab(tab_cfg)
        self._build_status()

    def _build_toolbar(self):
        p = self.palette
        bar = tk.Frame(self, bg=p["bg"])
        bar.pack(fill="x", padx=12, pady=(12, 4))

        tk.Label(bar, text="Nous Free Models", bg=p["bg"], fg=p["fg"],
                 font=("Segoe UI Semibold", 14)).pack(side="left")
        self.info = tk.Label(bar, text="", bg=p["bg"], fg=p["dim"], font=("Segoe UI", 9))
        self.info.pack(side="left", padx=(14, 0))

        combo = ttk.Combobox(
            bar, textvariable=self.combo_var, values=self.skins,
            state="readonly", width=22,
        )
        combo.bind("<<ComboboxSelected>>", self._on_skin_select)
        combo.pack(side="right", padx=(6, 0))

        self.auto_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            bar, text="Auto-refresh (15 min)", variable=self.auto_var,
            command=self._schedule_auto,
        ).pack(side="right")
        ttk.Button(bar, text="Copy slug", command=self.copy_selected).pack(side="right", padx=6)
        ttk.Button(bar, text="Refresh", command=self.refresh).pack(side="right", padx=(0, 6))

    def _build_catalog_tab(self, parent):
        wrap = tk.Frame(parent, bg=self._c("border"))
        wrap.pack(fill="both", expand=True, padx=0, pady=(2, 0))

        self.tree = ttk.Treeview(wrap, columns=COLS, show="headings", height=13)
        for col in COLS:
            self.tree.heading(col, text=col, anchor="w")
            self.tree.column(col, width=WIDTHS[col], anchor="w")
        self.tree.column("Model", minwidth=220, stretch=True)
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
            font=("Segoe UI", 9), anchor="w",
        )
        self.usage.pack(fill="x", padx=4, pady=(4, 2))

        inner = tk.Frame(wrap, bg=p["border"])
        inner.pack(fill="both", expand=True)

        self.tree2 = ttk.Treeview(inner, columns=CFG_COLS, show="headings", height=11)
        for col in CFG_COLS:
            self.tree2.heading(col, text=col, anchor="w")
            self.tree2.column(col, width=CFG_WIDTHS[col], anchor="w")
        self.tree2.column("Notes", minwidth=160, stretch=True)
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
            font=("Segoe UI", 9), anchor="w",
        )
        self.status.pack(fill="x", padx=14, pady=(0, 10))

    # ---------- data ----------

    def refresh(self):
        if self._busy:
            return
        self._busy = True
        self.status.configure(text="Contacting Nous Portal...", fg=self._c("dim"))

        def work():
            try:
                models, meta = nous_core.fetch_free_models()
            except Exception as exc:  # noqa: BLE001
                self.after(0, lambda: self._show_error(exc))
                return
            try:
                cfg_rows = hermes_state.configured_models()
                usage = hermes_state.recent_usage()
            except Exception:
                cfg_rows, usage = [], {"counts": {}, "fallbacks": [], "last": None}
            self.after(0, lambda: self._show(models, meta, cfg_rows, usage))

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

    def _show(self, models, meta, cfg_rows, usage):
        self._busy = False
        self.models = models
        self.meta = meta
        if hasattr(self, "tree"):
            self.tree.delete(*self.tree.get_children())
            for model in models:
                self._insert(model)
        self._render_config(cfg_rows, usage)

        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.status.configure(
            text=f"Last checked {stamp} · {meta['free_count']} free of {meta['catalog_rows']}",
            fg=self._c("ok"),
        )
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

    def _schedule_auto(self):
        if self._after_id:
            self.after_cancel(self._after_id)
            self._after_id = None
        if self.auto_var.get():
            self._after_id = self.after(REFRESH_MS, self._auto_tick)

    def _auto_tick(self):
        self.refresh()
        if self.auto_var.get():
            self._after_id = self.after(REFRESH_MS, self._auto_tick)


if __name__ == "__main__":
    try:
        App().mainloop()
    except KeyboardInterrupt:
        pass
