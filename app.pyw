#!/usr/bin/env python3w
"""Nous Free Models - a tiny dark window showing your live free-tier catalog."""
import datetime
import threading
import tkinter as tk
from tkinter import ttk

import nous_core

BG = "#0d1117"
CARD = "#161b22"
FG = "#e6edf3"
DIM = "#8b949e"
ACCENT = "#58a6ff"
GREEN = "#3fb950"
RED = "#f85149"
BORDER = "#30363d"

REFRESH_MS = 15 * 60 * 1000
COLS = ("Model", "Context", "Inputs", "Price", "Flags", "Source")
WIDTHS = {"Model": 320, "Context": 95, "Inputs": 140, "Price": 90, "Flags": 190, "Source": 110}


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Nous Free Models")
        self.geometry("960x440")
        self.minsize(760, 320)
        self.configure(bg=BG)
        self.models = []
        self._busy = False
        self._after_id = None

        self._style()
        self._build_toolbar()
        self._build_tree()
        self._build_status()
        self.after(200, self.refresh)

    def _style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "Treeview",
            background=CARD,
            foreground=FG,
            fieldbackground=CARD,
            borderwidth=0,
            rowheight=26,
            font=("Segoe UI", 10),
        )
        style.configure(
            "Treeview.Heading",
            background="#21262d",
            foreground=DIM,
            relief="flat",
            font=("Segoe UI Semibold", 9),
            padding=(6, 4),
        )
        style.map("Treeview", background=[("selected", "#1f6feb")], foreground=[("selected", FG)])
        style.configure("TButton", background="#21262d", foreground=FG, borderwidth=0, padding=6)
        style.map("TButton", background=[("active", "#2d333b")])
        style.configure("TCheckbutton", background=BG, foreground=DIM, font=("Segoe UI", 9))
        style.configure("Vertical.TScrollbar", background="#21262d", troughcolor=BG, borderwidth=0)

    def _build_toolbar(self):
        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=12, pady=(12, 4))

        tk.Label(
            bar, text="Nous Free Models", bg=BG, fg=FG, font=("Segoe UI Semibold", 14)
        ).pack(side="left")

        self.info = tk.Label(bar, text="", bg=BG, fg=DIM, font=("Segoe UI", 9))
        self.info.pack(side="left", padx=(14, 0))

        self.auto_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            bar, text="Auto-refresh (15 min)", variable=self.auto_var,
            command=self._schedule_auto,
        ).pack(side="right")

        ttk.Button(bar, text="Copy slug", command=self.copy_selected).pack(side="right", padx=6)
        ttk.Button(bar, text="Refresh", command=self.refresh).pack(side="right", padx=(0, 6))

    def _build_tree(self):
        wrap = tk.Frame(self, bg=BORDER)
        wrap.pack(fill="both", expand=True, padx=12, pady=(6, 4))

        self.tree = ttk.Treeview(wrap, columns=COLS, show="headings", height=14)
        for col in COLS:
            self.tree.heading(col, text=col, anchor="w")
            self.tree.column(col, width=WIDTHS[col], anchor="w")
        self.tree.column("Model", minwidth=220, stretch=True)
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda _e: self.copy_selected())

        scroll = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scroll.set)

    def _build_status(self):
        self.status = tk.Label(
            self, text="Checking...", bg=BG, fg=DIM, font=("Segoe UI", 9), anchor="w"
        )
        self.status.pack(fill="x", padx=14, pady=(0, 10))

    def refresh(self):
        if self._busy:
            return
        self._busy = True
        self.status.configure(text="Contacting Nous Portal...", fg=DIM)

        def work():
            try:
                models, meta = nous_core.fetch_free_models()
                self.after(0, lambda: self._show(models, meta, None))
            except Exception as exc:  # noqa: BLE001 - surface any fetch failure
                self.after(0, lambda: self._show([], {}, exc))

        threading.Thread(target=work, daemon=True).start()

    def _show(self, models, meta, error):
        self._busy = False
        self.models = models
        self.tree.delete(*self.tree.get_children())

        if error is not None:
            self.status.configure(text=f"Error: {error}", fg=RED)
            self.info.configure(text="")
            return

        for model in models:
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

        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.status.configure(text=f"Last checked {stamp} · account: free tier", fg=GREEN)
        self.info.configure(
            text=f"{meta['free_count']} of {meta['catalog_rows']} catalog models are free"
        )

    def copy_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        slug = self.tree.item(sel[0])["values"][0]
        self.clipboard_clear()
        self.clipboard_append(slug)
        self.status.configure(text=f"Copied: {slug}", fg=ACCENT)

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
