# Nous Free Models

A tiny desktop window that shows which Nous Portal models are free on your
account right now, and compares what Hermes has configured against them. It
unions two live sources, so stealth free SKUs that only exist in the inference
catalog are included too:

1. `GET portal.nousresearch.com/api/nous/recommended-models` (what the free tier may pick)
2. `GET inference-api.nousresearch.com/v1/models` (any row where prompt + completion price is 0)

No install, no dependencies beyond Python 3 with tkinter (stdlib only).

## Run it

Double-click **`run.ps1`** (right-click > Run with PowerShell) or **`run.cmd`**.
`run.cmd` keeps a console open so you can see tracebacks if something breaks.

## Views

- **Tabs** (default): *Free models* = the live catalog (context, inputs, price,
  flags, source); *In Hermes* = everything Hermes has pinned (`model.default`,
  auxiliary task models, fallback chain) classified as `FREE` / `PAID` /
  `MISSING`, plus recent per-model API call counts from `logs/agent.log`.
- **Side by side**: the checkbox under the content area splits the window into
  both tables at once, draggable divider. The choice persists in `ui_state.json`.
- **Stealth**: off-catalog models mined from `logs/agent.log` (`stealth/*` slugs),
  with mention counts and last-seen timestamps. Buttons: *Probe selected* /
  *Probe all* send a one-token chat request to test whether each model still
  answers (`alive` / `missing` / `rate_limited`), *Rescan log* re-mines the log,
  and *Auto probe (5 min)* keeps probing in the background. When a probe hits a
  429, any `alternates` listed in the error are added to the watchlist as new
  rows (origin `429 alternates`). Watches and probe results persist in
  `stealth_state.json` (gitignored).
- **Copy slug** (or double-click any row) copies the model string — e.g.
  `meituan/longcat-2.5:free` — ready to paste into `/model ...` or a config.

## What refreshes when

- **Refresh** button: checks everything (catalog + Hermes config + usage).
- **Auto models (15 min)**: only the free-model catalog, so the list stays
  current without touching your Hermes config or logs.
- **Deep check (4 h)**: only the Hermes config + usage counts.
- The status line shows how fresh each half is: `Models HH:MM · Config HH:MM`.

## Themes

The window follows whatever skin the desktop Hermes app is using, repolled every
~3 s, so `/skin slate` repaints this window too. Sources, in order:

- the Hermes skin engine (default, ares, mono, slate, daylight, warm-lightmode,
  poseidon, sisyphus, charizard, plus any user skins in `%LOCALAPPDATA%\hermes\skins`),
- the desktop-only presets the CLI engine doesn't expose (cyberpunk, midnight,
  ember, nous, github, catppuccin, everforest, solarized).

Pick a specific skin from the dropdown to pin it instead of following; the choice
is stored in `theme_choice.json`. Light skins flip the whole window to a light
palette. If neither source resolves, a built-in dark palette is used.

## AI notice & license

This project was created with AI assistance (Hermes Agent). See `NOTICE.md`;
licensed under the MIT License (`LICENSE`).

## Where the token comes from

The app reads your existing Hermes login from
`%LOCALAPPDATA%\hermes\auth.json` (`providers.nous.access_token`). If it reports
an auth error, re-login to the Portal through Hermes (`hermes setup`) and try again.

## Files

| File | Purpose |
|---|---|
| `app.pyw` | The tkinter window (tabs/split, toolbar, timers, About) |
| `nous_core.py` | Auth lookup + the two API calls + union logic |
| `hermes_state.py` | Reads Hermes config via `hermes config get`; parses `agent.log` usage |
| `theme.py` | Skin engine + desktop preset palettes, override persistence |
| `alerts.py` | Per-role transition detection + taskbar flash helper |
| `stealth.py` | Log mining, liveness probes, 429-alternate discovery |
| `run.ps1` / `run.cmd` | Launchers that find a Python automatically |
| `LICENSE` / `NOTICE.md` | MIT license + AI-assistance notice |
