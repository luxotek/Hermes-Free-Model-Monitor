# Project Status — Hermes Free Model Monitor

Last updated: 2026-11-14

Current stage: **0–5 complete; 6 (local models) parked**

Remote: **https://github.com/luxotek/Hermes-Free-Model-Monitor** (renamed from `herms-free-mode`; now public; pushed)

## Rename & release (2026-11-14)
- App renamed **Nous Free Models → Hermes Free Model Monitor** (HFMM) everywhere:
  window title/header, Settings dialog, About blurb, docs, user agents (`hfmm/1.0`).
- Repo renamed `herms-free-mode` → `Hermes-Free-Model-Monitor` and made public.
- LICENSE rewritten: free personal use; sharing/forking/editing allowed with credit
  to luxotek + AI notice; no commercial sale by others; luxotek keeps all commercial rights.
- Start Menu shortcut rebuilt as "Hermes Free Model Monitor.lnk".
- Portable Windows build: `dist/Hermes Free Model Monitor.exe` (PyInstaller onefile,
  ~12 MB, no Python needed on the target; requires an existing Hermes install).
- Release **v0.1.0** published with the exe + SHA256SUMS.txt:
  https://github.com/luxotek/Hermes-Free-Model-Monitor/releases/tag/v0.1.0

## Roadmap

- [x] 0. Safety net — git repo, status file, `.gitignore`
- [x] 1. Theme follow (Hermes skin engine) + manual override picker
- [x] 2. Config vs available comparison (default, aux pins, fallback chain, actual usage)
- [x] 3. Alerts + model actions (death notices, set main model, copy slug, session hint)
- [x] 3b. Active-model death alert + return suppression
- [x] 4. Stealth watch (log-mined watchlist, liveness probes, 429 `alternates` discovery)
- [x] 5a. InfoSpace (alert history strip, contextual empty states)
- [x] 5b. Bubble notifications (app-anchored bottom-right stack)
- [ ] 6. Parked: local model scan/load — SimSense explicitly out of scope

## Stage 4 complete (2026-11-14)
- New `stealth.py`: mines `logs/agent.log` for `stealth/*` slugs (mention count + last-seen),
  probes each with a one-token chat completion (`alive` / `missing` / `rate_limited`), and
  folds any `alternates` from 429 error bodies into the watchlist.
- New "Stealth" tab (third pane in side-by-side mode): buttons *Probe selected* /
  *Probe all* / *Rescan log*, an *Auto probe (5 min)* toggle, color-coded state column,
  and per-row detail. State persists in `stealth_state.json` (gitignored).
- Verified live: mined `stealth/crouton-alpha` (428 mentions, last seen 2026-11-13 20:58);
  probe returned HTTP 404 (currently gone).

## Stage 5 complete (2026-11-14)
- New `bubbles.py`: borderless, always-on-top toast cards anchored to the app window's
  bottom-right, stacking upward (newest at the bottom), auto-dismiss by severity
  (critical 9 s, warn 7 s, other 6 s), click-to-close. Square corners (DPI-safe).
- Options row gains a **Bubbles** checkbox (persisted in `ui_state.json`). Bubbles fire on
  model alerts, active-model loss, probe summaries, and refresh errors.
- Info strip under the toolbar: `N free of M · deep HH:MM · stealth N` plus a
  `History (N)` button that expands an alert-history list (last 8, severity-colored,
  capped at 20 entries).
- Empty-state infospace: each pane shows a centered tip block instead of dead whitespace
  when it has nothing to show (catalog empty / config empty / no stealth watches).
- Verified live: startup alert for `fallback #2` raised both the alert bar, history entry,
  and a bubble that auto-dismissed; split/tab rebuild stays clean.

## Stage 5 follow-ups (2026-11-14)
- Split/side-by-side mode removed (3 panes do not fit typical monitors); tabs + a bottom
  master-detail panel instead.
- Detail panel: selecting any row (all three tabs) shows its full info stacked vertically.
- Responsive columns: each tab hides low-priority columns below width thresholds
  (catalog Price<1000 / Flags<1200 / Source<1400; config Provider<950 / Notes<1250;
  stealth Mentions<800 / Last seen<1000 / Origin<1250 / Detail<1450).
- Default window size adapts to the screen (78% width capped 1400 px, 85% height capped
  860 px), centered at launch.
- Font bump across status strip, history, alerts, usage line, detail panel (SZ_INFO = 14);
  bubbles widened to 420 px with 14–15 pt text.
- LICENSE replaced: MIT → source-available, personal-use (credit + AI notice required). Later
  revised (2026-11-14): free for personal use, sharing/forking/editing welcome with credit +
  AI notice, no commercial sale by others, luxotek retains all commercial rights (NOTICE.md).
  About dialog updated (credit line, terms, centered over parent, non-resizable, Esc closes).
- Start Menu shortcut created: "Hermes Free Model Monitor.lnk" → project venv pythonw + app.pyw.

## UX pass (2026-11-14, same night)
- About → **Settings**: toolbar button now opens one dialog holding Preferences
  (Auto models / Deep check / Bubbles checkboxes moved off the bottom row), Alert
  history (last 20, severity-colored), and the About block.
- Single clear status line replaces the info strip + bottom timers text:
  `N free models of M total · catalog updated HH:MM · Hermes config checked HH:MM ·
  stealth watch: N`. The "deep HH:MM" and duplicated "3 of 401" texts are gone.
- History button removed from the toolbar (it lived under Settings before); action
  buttons grouped together: Refresh / Copy model name / Set main model.
- Alert strips at the bottom removed entirely: alerts now surface as colored
  bubbles (bottom-right) plus the history list in Settings.
- All three tables auto-fit their columns to content (no dead space) with a
  horizontal scrollbar when the window is narrower than the table.
- Copy renamed "Copy model name"; toolbar "Use as main" renamed "Set main model";
  both flash the result in the status line ("Copied: <slug>", "Main model set to …").
- About text trimmed to end at "redistribution."; LICENSE and NOTICE.md are
  clickable links in Settings (open local file, fall back to the GitHub page).

## Theme follow + contrast fix (2026-11-14)
- Root cause of "themes aren't following": the desktop app stores its theme in
  `%LOCALAPPDATA%\hermes\ui-preferences.json` (`hermes-desktop-theme-v2`), while the
  monitor was reading the CLI config (`display.skin`), which the desktop does not
  update live. Auto mode now prefers the desktop's stored theme, then falls back to
  the CLI skin engine; the dropdown shows what is followed (`Auto (cyberpunk)`).
- Some presets looked washed out on their own (everforest/catppuccin/daylight/
  warm-lightmode had card≈bg or dim text at <2:1 contrast). Palettes are now
  normalised: fg ≥ 4.5:1, dim ≥ 3:1, accent ≥ 3:1 vs background, card fill pushed
  away from the page background (≥1.18:1), selection guaranteed distinguishable.

## Scrollbar fix (2026-11-14)
- Vertical + horizontal scrollbars were always packed, so they appeared even when
  the table had few rows (and overlapped notification bubbles).
- Both now sync against real overflow (row count / column sum vs viewport) after
  renders, on `<Configure>`, and via a 2 s self-correcting tick. Container frames
  use the page background so no seam sits next to a scrollbar.

## Enhancements landed (post stage 2)

- Second font/accessibility bump across all widgets (title 20, body 13, tree 14, head 13, roomier rows).
- Side-by-side view toggle alongside tabs (`ui_state.json`, gitignored), draggable divider.
- Split timers: "Auto models (15 min)" re-checks only the catalog; "Deep check (4 h)"
  re-reads only Hermes config + usage. Manual Refresh still does both. Status line shows
  per-half freshness ("Models HH:MM · Config HH:MM").
- Desktop preset themes exposed in the dropdown (cyberpunk, midnight, ember, nous, github,
  catppuccin, everforest, solarized) parsed live from `apps/shared/src/theme-presets.ts`.
- About dialog + source-available LICENSE + NOTICE.md (AI-assistance notice).

## Decisions

- Cloud-only for this app; no local model loading for now.
- Themes: live-follow the installed Hermes skin engine, with an `Auto (follow Hermes)`
  mode plus a manual per-skin override; engine names win over same-named presets.
  Manual picks persist in `theme_choice.json` (gitignored).
- Work proceeds in git-committed stages so any stage can be reverted independently.
- Config reading uses `hermes config get <key>` (never hand-edits config.yaml).
- Stage 2 finding: `fallback #2` (`reflection/beam-1.0-501b-a23b:free`) is listed but no
  longer free — classified PAID, shown color-coded.

## GitHub / token handling

- Token lives in `%USERPROFILE%\.github-pat`; never pasted in chat, never committed.
- Pushes authenticate through `%USERPROFILE%\.git-nous-helper.sh`, a tiny credential
  helper that echoes the token from that file:
  `git -c credential.helper="!C:/Users/Luxotek/.git-nous-helper.sh" push <url> main`
- Commit author/committer email rewritten to `278851+luxotek@users.noreply.github.com`:
  GitHub rejected the original push because commits exposed the user's private email
  (`luxotek@outlook.com`) under their "keep my email private" setting.
- Push required a lease-guarded force update once (remote had GitHub's boilerplate
  "Initial commit"); history is now linear on top of it.

## Deferred

- Further UI sizing/spacing polish and side-by-side refinements — sizing settled for now.

## Next steps

1. Nothing queued — stages 0–4 are complete; stage 5 (local model scan/load) stays parked.

## Open questions

- Whether Hermes' own API calls can be intercepted to auto-capture 429 `alternates`
  (currently only app-initiated probes feed discovery).
- Probe cadence default for stealth watches (manual now; 5 min opt-in toggle available).
