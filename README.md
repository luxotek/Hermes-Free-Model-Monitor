# Hermes Free Model Monitor

Checks Hermes's 400+ model list to find which free models are live right now,
so you can set a reliable main model and fallback chain. A tiny desktop window
(shortened **HFMM**, the "Hermes FMM companion app") that unions two live
sources and keeps only the models worth building a long-term chain on:

1. `GET portal.nousresearch.com/api/nous/recommended-models` (what the free tier may pick)
2. `GET inference-api.nousresearch.com/v1/models` (any row where prompt + completion price is 0)
3. `GET openrouter.ai/api/v1/models` (the `:free` models your key can actually call)

Previews and anything with an expiration date are dropped from the free list; the
config tab still flags them if you already have one pinned.

No install, no dependencies beyond Python 3 with tkinter (stdlib only).
A self-contained Windows `.exe` is attached to the GitHub release for machines
that already have Hermes installed; the source run below is always current.

## Run it

Double-click **`run.ps1`** (right-click > Run with PowerShell) or **`run.cmd`**.
`run.cmd` keeps a console open so you can see tracebacks if something breaks.

## Views

- **Tabs** (default): *Free models* = the live catalog (context, inputs, output,
  released, flags, source), permanent free models only — previews and anything
  with an expiration date are left off so the list stays safe to build a chain
  on;
  *Hermes config* = everything Hermes has pinned (`model.default`, auxiliary
  task models, fallback chain) classified as `FREE` / `PAID` / `MISSING`, with
  context and flags (vision / video / compaction) filled in from the catalog
  where known, a **Temp** column flagging previews and expiry dates, plus recent
  per-model API call counts from `logs/agent.log`.
- **Additional info**: select a row (any tab), then use the button above the
  status line or the right-click menu entry to open a popup sheet with the full
  picture — column values, moderation/reasoning/free-tier flags, the catalog
  description and any benchmark scores. Right-justified to the window, vertically
  centred, and never taller than the tab panel.
- **Bubbles**: self-contained toast cards in the window's bottom-right corner
  (UniGetUI-style): newest at the bottom, stack upward, auto-dismiss by severity,
  click to close. Fired on model alerts, active-model loss, probe summaries, and
  refresh errors. Alerts also land in **Settings → Alert history**.
- **Settings** (top-right button): preferences (auto-refresh timers, bubbles),
  alert history, and the About block with links to `LICENSE` / `NOTICE.md`.
- **Window geometry** is remembered: it reopens at the size and position you
  left it in (saved in `ui_state.json`, debounced while resizing). If the saved
  spot is off-screen, it keeps the size and centers instead.
- **Columns auto-fit** their content; if the window is narrower than the table,
  a horizontal scrollbar appears (no dead space).
- **Empty states**: panes with nothing to show display a centered tip block instead
  of dead whitespace.
- **Fallback chain editing**
  - *Free models* tab: right-click a model → **Add as new fallback** (at the end
    or at the top) or **Replace fallback** (pick the slot whose model to swap).
  - *Hermes config* tab: drag fallback rows into a new order (main and aux rows
    stay put), or right-click a fallback row → **Remove fallback #N**.
  - Changes are written with `hermes config set fallback_providers`; replaced
    entries keep any extra keys (`base_url`, `api_key`, …).
- **Copy model name**: right-click a row (or double-click it) to copy the model
  string — e.g. `meituan/longcat-2.5:free` — ready to paste into `/model ...`
  or a config.

## What refreshes when

- **Refresh** button: checks everything (catalog + Hermes config + usage).
- **Auto models (15 min)**: only the free-model catalog, so the list stays
  current without touching your Hermes config or logs.
- **Deep check (4 h)**: only the Hermes config + usage counts.
- The bottom status line shows it plainly: `N free models of M total · catalog
  updated HH:MM · Hermes config checked HH:MM`.

## Themes

The window follows whatever skin the desktop Hermes app is using, repolled every
~3 s, so `/skin slate` repaints this window too. Sources, in order:

- the desktop app's own theme choice (`%LOCALAPPDATA%\hermes\ui-preferences.json`,
  key `hermes-desktop-theme-v2`) — this is what the desktop actually uses,
  including themes like cyberpunk that the CLI config doesn't know about,
- the Hermes skin engine (default, ares, mono, slate, daylight, warm-lightmode,
  poseidon, sisyphus, charizard, plus any user skins in `%LOCALAPPDATA%\hermes\skins`),
- the desktop-only presets the CLI engine doesn't expose (cyberpunk, midnight,
  ember, nous, github, catppuccin, everforest, solarized).

The dropdown shows the followed theme while in Auto mode (e.g. `Auto (cyberpunk)`);
changes apply within one poll (~3 s), no restart needed. Picking a specific theme
from the dropdown pins it instead of following (stored in `theme_choice.json`).
Palette roles are normalised for contrast (text, dim labels, accents, and panel
fills are nudged until they clear minimum contrast against the background), so
light and dark presets both read correctly. If neither source resolves, a
built-in dark palette is used.

## AI notice & license

This project was created with AI assistance (Hermes Agent). See `NOTICE.md`.
Free for personal use; sharing, forking, and modifying are welcome as long as
credit to luxotek and the AI notice stay attached. Not for sale as a commercial
product by anyone else; luxotek retains all commercial rights (`LICENSE`).

## Where the token comes from

The app reads your existing Hermes login from
`%LOCALAPPDATA%\hermes\auth.json` (`providers.nous.access_token`). If it reports
an auth error, re-login to the Portal through Hermes (`hermes setup`) and try again.

## OpenRouter free models

When a valid OpenRouter token is present (from the Hermes `.env`, or `auth.json`'s
credential pool), the **Free models** tab also pulls OpenRouter's
`GET /api/v1/models` catalog. A model is listed as free when it carries the
`:free` suffix, or charges `$0` for input, or `$0` for output:

- OR's official free marker is the `:free` suffix (7 models today);
- `scaledown/extract` and `scaledown/summarize` are `$0` to *complete* (input
  costs a few hundred-thousandths of a cent), so they're included too;
- the count grows and shrinks as OpenRouter onboard new providers — it is a live
  number, not a fixed list.

> **Why isn't it 25?** OpenRouter's *website* (openrouter.ai/collections/free-models)
> shows its own usage-ranked free collection; that curated view includes
> effectively-free models with tiny-but-nonzero endpoint prices and models the
> authenticated API payload doesn't return. HFMM lists the *live API* count, so
> it reflects what OpenRouter publishes right now.

## Files

| File | Purpose |
|---|---|
| `app.pyw` | The tkinter window (tabs, Additional-info popup, toolbar, timers, Settings/About) |
| `nous_core.py` | Auth lookup + the two API calls + union logic |
| `hermes_state.py` | Reads Hermes config via `hermes config get`; parses `agent.log` usage |
| `theme.py` | Skin engine + desktop preset palettes, override persistence |
| `alerts.py` | Per-role transition detection + taskbar flash helper |
| `bubbles.py` | Bottom-right bubble notification stack |
| `run.ps1` / `run.cmd` | Launchers that find a Python automatically |
| `LICENSE` / `NOTICE.md` | Source-available non-commercial license + AI-assistance notice |
| `dist/` | PyInstaller output — the portable Windows exe |
