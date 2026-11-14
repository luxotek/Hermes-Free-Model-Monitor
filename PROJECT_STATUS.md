# Project Status — Nous Free Models

Last updated: 2026-11-14

Current stage: **0–5 complete; 6 (local models) parked**

Remote: **https://github.com/luxotek/herms-free-mode** (pushed)

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

## Enhancements landed (post stage 2)

- Second font/accessibility bump across all widgets (title 20, body 13, tree 14, head 13, roomier rows).
- Side-by-side view toggle alongside tabs (`ui_state.json`, gitignored), draggable divider.
- Split timers: "Auto models (15 min)" re-checks only the catalog; "Deep check (4 h)"
  re-reads only Hermes config + usage. Manual Refresh still does both. Status line shows
  per-half freshness ("Models HH:MM · Config HH:MM").
- Desktop preset themes exposed in the dropdown (cyberpunk, midnight, ember, nous, github,
  catppuccin, everforest, solarized) parsed live from `apps/shared/src/theme-presets.ts`.
- About dialog + MIT LICENSE + NOTICE.md (AI-assistance notice).

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
