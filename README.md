# Nous Free Models

A tiny dark desktop window that shows which Nous Portal models are free on your
account right now. It unions two live sources, so stealth free SKUs that only
exist in the inference catalog are included too:

1. `GET portal.nousresearch.com/api/nous/recommended-models` (what the free tier may pick)
2. `GET inference-api.nousresearch.com/v1/models` (any row where prompt + completion price is 0)

No install, no dependencies beyond Python 3 with tkinter (stdlib only).

## Run it

Double-click **`run.ps1`** (right-click > Run with PowerShell) or **`run.cmd`**.
`run.cmd` keeps a console open so you can see tracebacks if something breaks.

- **Refresh** re-checks both endpoints.
- **Copy slug** (or double-click a row) copies the model string to the clipboard.
- **Auto-refresh** polls every 15 minutes while the box is ticked.

## Where the token comes from

The app reads your existing Hermes login from
`%LOCALAPPDATA%\hermes\auth.json` (`providers.nous.access_token`). If it reports
an auth error, re-login to the Portal through Hermes (`hermes setup`) and try again.

## Files

| File | Purpose |
|---|---|
| `app.pyw` | The tkinter window |
| `nous_core.py` | Auth lookup + the two API calls + union logic |
| `run.ps1` / `run.cmd` | Launchers that find a Python automatically |
