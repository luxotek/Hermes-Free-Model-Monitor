"""Resolve the installed Hermes skin into a palette for the window.

Two sources, in order:
1. The Hermes CLI skin engine (`hermes_cli.skin_engine`) — what the desktop app
   is actually using, including user skins in `<home>/skins/*.yaml`.
2. The desktop-only presets (`apps/shared/src/theme-presets.ts`) — themes like
   cyberpunk/midnight/ember that the desktop ships but the CLI engine lacks.

Falls back to a built-in dark palette if neither is reachable.
"""
import json
import os
import re
import sys

import nous_core

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
    """Hermes home: the directory holding auth.json, else the install default."""
    return nous_core.hermes_home() or (
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


# ---------- colour helpers ----------

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
    return _hex(tuple(c * factor for c in _rgb(value)))


def _blend(value, target, weight):
    a, b = _rgb(value), _rgb(target)
    return _hex(tuple(a[i] * (1 - weight) + b[i] * weight for i in range(3)))


def _contrast(a, b):
    la, lb = _lum(_rgb(a)), _lum(_rgb(b))
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _ensure(color, bg, minimum, dark_bg):
    """Step a colour toward white/black until it clears `minimum` against bg."""
    c = color
    factor = 1.14 if dark_bg else 0.88
    for _ in range(32):
        if _contrast(c, bg) >= minimum:
            return c
        c = _adjust(c, factor)
    return c


def _separate(value, bg, minimum=1.18):
    """Push a fill colour away from the page background enough to read as a panel."""
    dark_bg = _lum(_rgb(bg)) <= 0.45
    c = value
    factor = 1.22 if dark_bg else 0.82
    for _ in range(32):
        if _contrast(c, bg) >= minimum:
            return c
        c = _adjust(c, factor)
    return c


# ---------- source 1: CLI skin engine ----------

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
    card = _separate(
        get("completion_menu_bg") or get("status_bar_bg") or _adjust(bg, 1.15 if not light else 0.92),
        bg, 1.18,
    )
    accent = _ensure(get("ui_accent") or get("banner_accent") or "#58a6ff", bg, 3.0, not light)
    dim = _ensure(get("status_bar_dim") or get("banner_dim") or "#8b949e", bg, 3.0, not light)
    border = _ensure(
        get("session_border") or get("input_rule") or get("banner_border") or "#30363d",
        bg, 1.3, not light,
    )
    fg = _ensure(
        get("banner_text") or get("ui_text") or get("status_bar_text") or "#e6edf3",
        bg, 4.5, not light,
    )
    selection = get("selection_bg") or _blend(accent, bg, 0.35)
    if _contrast(selection, bg) < 1.2:
        selection = _blend(accent, bg, 0.45 if not light else 0.30)

    return {
        "bg": bg,
        "card": card,
        "border": border,
        "fg": fg,
        "dim": dim,
        "accent": accent,
        "ok": get("ui_ok") or "#3fb950",
        "warn": get("ui_warn") or "#d29922",
        "error": get("ui_error") or "#f85149",
        "selection": selection,
        "head_bg": _adjust(card, 1.12 if not light else 0.96),
        "head_fg": dim,
    }


# ---------- source 2: desktop-only presets ----------

_preset_cache = {"mtime": None, "palettes": {}}


def _presets_path():
    return os.path.join(
        _hermes_home(), "hermes-agent", "apps", "shared", "src", "theme-presets.ts"
    )


def _block(text, start):
    """`text[start]` sits just past an opening brace; return (body, end_index)."""
    depth, index = 1, start
    while index < len(text) and depth:
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        index += 1
    return text[start:index - 1], index


def _color_map(block):
    return dict(re.findall(r"([A-Za-z]+):\s*'(#[0-9a-fA-F]{3,8})'", block))


def _load_presets():
    """Parse each preset's `{ colors, darkColors }` out of theme-presets.ts."""
    path = _presets_path()
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {}
    if _preset_cache["mtime"] == mtime and _preset_cache["palettes"]:
        return _preset_cache["palettes"]
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return {}

    palettes = {}
    entry = re.compile(r"^  (['\"]?)([A-Za-z][A-Za-z0-9-]*)\1:\s*\{", re.M)
    for match in entry.finditer(text):
        body, _ = _block(text, match.end())
        found = {}
        for key in ("colors", "darkColors"):
            sub = re.search(rf"\b{key}:\s*\{{", body)
            if sub:
                block, _ = _block(body, sub.end())
                colors = _color_map(block)
                if colors:
                    found[key] = colors
        if found.get("colors"):
            palettes[match.group(2)] = found

    _preset_cache["mtime"] = mtime
    _preset_cache["palettes"] = palettes
    return palettes


def preset_names():
    return sorted(_load_presets())


def preset_palette(name, dark=True):
    """Palette for a desktop preset.

    `dark` picks the preset's hand-tuned dark variant when it ships one. The
    light-mode presets (github, nous, catppuccin, everforest, solarized) are
    white by default, which reads wrong on a dark-mode desktop.
    """
    preset = _load_presets().get(name) or {}
    colors = preset.get("darkColors") if dark else preset.get("colors")
    colors = colors or preset.get("colors")
    if not colors:
        return None
    get = colors.get
    bg = get("background") or get("sidebarBackground") or "#0d1117"
    dark_bg = _lum(_rgb(bg)) <= 0.45
    card = _separate(get("card") or _adjust(bg, 1.12), bg, 1.18)
    accent = _ensure(get("ring") or get("primary") or "#58a6ff", bg, 3.0, dark_bg)
    fg = _ensure(get("foreground") or get("cardForeground") or "#e6edf3", bg, 4.5, dark_bg)
    dim = _ensure(get("mutedForeground") or "#8b949e", bg, 3.0, dark_bg)
    border = _ensure(get("border") or _adjust(bg, 1.25), bg, 1.3, dark_bg)
    selection = get("accent") or _blend(accent, bg, 0.35)
    if _contrast(selection, bg) < 1.2:
        selection = _blend(accent, bg, 0.45 if dark_bg else 0.30)
    return {
        "bg": bg,
        "card": card,
        "border": border,
        "fg": fg,
        "dim": dim,
        "accent": accent,
        "ok": "#3fb950",
        "warn": "#d29922",
        "error": get("destructive") or "#f85149",
        "selection": selection,
        "head_bg": _adjust(card, 1.12),
        "head_fg": dim,
    }


# ---------- public API ----------

def _engine_names():
    try:
        return {s["name"] for s in _import_engine().list_skins()}
    except Exception:
        return set(FALLBACK_NAMES)


def _active_name():
    try:
        return _import_engine().get_active_skin_name()
    except Exception:
        return None


def desktop_theme_name():
    """Theme selected in the Hermes desktop app (ui-preferences.json).

    The desktop writes its choice here; the CLI config (`display.skin`) is not
    updated live, so this is the source of truth for following the app.
    """
    path = os.path.join(_hermes_home(), "ui-preferences.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    value = (data.get("values") or {}).get("hermes-desktop-theme-v2")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


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
    names = []
    try:
        names.extend(s["name"] for s in _import_engine().list_skins())
    except Exception:
        names.extend(FALLBACK_NAMES)
    for name in preset_names():
        if name not in names:
            names.append(name)
    return names


def resolve(choice=None):
    """Return (palette, meta)."""
    choice = choice or load_choice()
    override = choice.get("mode") == "skin"
    if override:
        name = choice.get("name")
    else:
        # Follow the desktop app first; fall back to whatever the CLI reports.
        name = desktop_theme_name() or _active_name()
    engine_names = _engine_names()

    if name and name in engine_names:
        try:
            cfg = _import_engine().load_skin(name)
            return build_palette(cfg), {"source": "engine", "skin": cfg.name}
        except Exception:
            pass

    if name:
        palette = preset_palette(name)
        if palette:
            return palette, {"source": "preset", "skin": name}

    if override:
        return dict(FALLBACK_PALETTE), {"source": "fallback", "skin": name or "?"}

    try:
        cfg = _import_engine().get_active_skin()
        return build_palette(cfg), {"source": "engine", "skin": cfg.name}
    except Exception:
        return dict(FALLBACK_PALETTE), {"source": "fallback", "skin": "n/a"}