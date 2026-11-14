"""Resolve the installed Hermes skin engine into a palette for the window.

Reads whatever skin the desktop app is currently using (live), unless the user
picked a specific skin in the app's dropdown. Falls back to a built-in dark
palette if the Hermes source tree can't be imported.
"""
import json
import os
import sys

CHOICE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "theme_choice.json")

FALLBACK_PALETTE = {
    "bg": "#0d1117", "card": "#161b22", "border": "#30363d",
    "fg": "#e6edf3", "dim": "#8b949e", "accent": "#58a6ff",
    "ok": "#3fb950", "warn": "#d29922", "error": "#f85149",
    "selection": "#1f6feb", "head_bg": "#21262d", "head_fg": "#8b949e",
}

FALLBACK_NAMES = [
    "default", "ares", "mono", "slate", "daylight",
    "warm-lightmode", "poseidon", "sisyphus", "charizard",
]


def _hermes_home():
    return (
        os.environ.get("HERMES_HOME")
        or os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes")
        or os.path.expanduser("~/.hermes")
    )


def _import_engine():
    home = _hermes_home()
    os.environ["HERMES_HOME"] = home
    repo = os.path.join(home, "hermes-agent")
    if repo not in sys.path:
        sys.path.insert(0, repo)
    from hermes_cli import skin_engine

    return skin_engine


def _rgb(value):
    try:
        value = str(value).strip().lstrip("#")
        if len(value) == 3:
            value = "".join(ch * 2 for ch in value)
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, TypeError):
        return (17, 17, 17)


def _hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(c))) for c in rgb)


def _lum(rgb):
    r, g, b = (c / 255 for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _adjust(value, factor):
    """factor < 1 darkens toward black, > 1 lightens toward white."""
    return _hex(tuple(c * factor for c in _rgb(value)))


def _blend(value, target, weight):
    a, b = _rgb(value), _rgb(target)
    return _hex(tuple(a[i] * (1 - weight) + b[i] * weight for i in range(3)))


def build_palette(cfg):
    colors = dict(cfg.colors)
    probe = (
        colors.get("background")
        or colors.get("status_bar_bg")
        or colors.get("completion_menu_bg")
        or "#111111"
    )
    light = _lum(_rgb(probe)) > 0.55
    merged = {**colors, **(cfg.light_colors if light else cfg.dark_colors)}
    get = merged.get

    bg = get("background") or _adjust(get("status_bar_bg") or probe, 0.82 if not light else 1.05)
    card = get("completion_menu_bg") or get("status_bar_bg") or _adjust(bg, 1.15 if not light else 0.92)
    accent = get("ui_accent") or get("banner_accent") or "#58a6ff"
    dim = get("status_bar_dim") or get("banner_dim") or "#8b949e"
    border = get("session_border") or get("input_rule") or get("banner_border") or "#30363d"

    return {
        "bg": bg,
        "card": card,
        "border": border,
        "fg": get("banner_text") or get("ui_text") or get("status_bar_text") or "#e6edf3",
        "dim": dim,
        "accent": accent,
        "ok": get("ui_ok") or "#3fb950",
        "warn": get("ui_warn") or "#d29922",
        "error": get("ui_error") or "#f85149",
        "selection": get("selection_bg") or _blend(accent, bg, 0.35),
        "head_bg": _adjust(card, 1.12 if not light else 0.96),
        "head_fg": dim,
    }


def load_choice():
    try:
        with open(CHOICE_FILE, encoding="utf-8") as fh:
            choice = json.load(fh)
        if choice.get("mode") in ("auto", "skin"):
            return choice
    except (OSError, ValueError):
        pass
    return {"mode": "auto"}


def save_choice(choice):
    try:
        with open(CHOICE_FILE, "w", encoding="utf-8") as fh:
            json.dump(choice, fh)
    except OSError:
        pass


def skin_names():
    try:
        return [s["name"] for s in _import_engine().list_skins()]
    except Exception:
        return list(FALLBACK_NAMES)


def resolve(choice=None):
    """Return (palette, meta)."""
    try:
        engine = _import_engine()
    except Exception:
        return dict(FALLBACK_PALETTE), {"source": "fallback", "skin": "n/a"}

    choice = choice or load_choice()
    name = choice.get("name") if choice.get("mode") == "skin" else None
    try:
        cfg = engine.load_skin(name) if name else engine.get_active_skin()
    except Exception:
        return dict(FALLBACK_PALETTE), {"source": "fallback", "skin": name or "auto"}
    return build_palette(cfg), {"source": "engine", "skin": cfg.name}
