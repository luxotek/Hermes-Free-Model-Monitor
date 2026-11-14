"""Bottom-right bubble notification stack (self-contained, UniGetUI-style)."""
import tkinter as tk

GAP = 10
WIDTH = 340
LEVEL_COLORS = ("critical", "warn", "ok", "info")
TIMEOUTS = {"critical": 9000, "warn": 7000}


class BubbleStack:
    """Borderless toast cards anchored to the bottom-right of a master window."""

    def __init__(self, master, palette, enabled):
        self.master = master
        self.palette = palette    # callable -> palette dict
        self.enabled = enabled    # callable -> bool
        self.items = []

        master.bind("<Configure>", lambda _e: self._restack(), add="+")
        master.bind("<Unmap>", lambda _e: self._set_visible(False), add="+")
        master.bind("<Map>", lambda _e: self._set_visible(True), add="+")

    def show(self, title, message, level="info", timeout=None):
        if level not in LEVEL_COLORS:
            level = "info"
        if not self.enabled():
            return None
        pal = self.palette()
        color = {
            "critical": pal["error"], "warn": pal["warn"],
            "ok": pal["ok"], "info": pal["accent"],
        }[level]
        if timeout is None:
            timeout = TIMEOUTS.get(level, 6000)

        win = tk.Toplevel(self.master)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=pal["border"])

        card = tk.Frame(win, bg=pal["card"])
        card.pack(fill="both", expand=True, padx=1, pady=1)

        edge = tk.Frame(card, bg=color, width=4)
        edge.pack(side="left", fill="y")

        inner = tk.Frame(card, bg=pal["card"])
        inner.pack(side="left", fill="both", expand=True, padx=(10, 8), pady=(7, 7))

        head = tk.Frame(inner, bg=pal["card"])
        head.pack(fill="x")
        tk.Label(
            head, text=title, bg=pal["card"], fg=pal["fg"],
            font=("Segoe UI Semibold", 11), anchor="w",
        ).pack(side="left", fill="x", expand=True)
        close = tk.Label(
            head, text="✕", bg=pal["card"], fg=pal["dim"],
            font=("Segoe UI", 10), cursor="hand2",
        )
        close.pack(side="right")

        tk.Label(
            inner, text=message, bg=pal["card"], fg=pal["dim"],
            font=("Segoe UI", 10), justify="left", anchor="w",
            wraplength=WIDTH - 44,
        ).pack(fill="x", pady=(2, 0))

        for widget in (win, card, edge, inner, head, close):
            widget.bind("<Button-1>", lambda _e, w=win: self.close(w))

        win.update_idletasks()
        item = {"win": win, "height": max(win.winfo_reqheight(), 56)}
        self.items.append(item)
        win.after(timeout, lambda w=win: self.close(w))
        self._restack()
        return item

    def close(self, win):
        item = next((it for it in self.items if it["win"] == win), None)
        if item is None:
            return
        self.items.remove(item)
        try:
            win.destroy()
        except Exception:
            pass
        self._restack()

    def _set_visible(self, visible):
        for item in self.items:
            try:
                if visible:
                    item["win"].deiconify()
                else:
                    item["win"].withdraw()
            except Exception:
                pass
        if visible:
            self._restack()

    def _restack(self):
        if not self.items:
            return
        try:
            base_x = self.master.winfo_rootx() + self.master.winfo_width() - WIDTH - GAP
            base_y = self.master.winfo_rooty() + self.master.winfo_height() - GAP
        except Exception:
            return
        y = base_y
        for item in reversed(self.items):
            y -= item["height"]
            try:
                item["win"].geometry(f"{WIDTH}x{item['height']}+{base_x}+{y}")
            except Exception:
                pass
            y -= GAP