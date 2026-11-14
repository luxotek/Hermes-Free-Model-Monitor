# Project Status — Nous Free Models

Last updated: 2026-11-14

Current stage: **2 complete + enhancement pass landed, starting 3**

Remote: **https://github.com/luxotek/herms-free-mode** (pushed)

## Roadmap

- [x] 0. Safety net — git repo, status file, `.gitignore`
- [x] 1. Theme follow (Hermes skin engine) + manual override picker
- [x] 2. Config vs available comparison (default, aux pins, fallback chain, actual usage)
- [ ] 3. Alerts + model actions (death notices, set main model, copy slug, session hint)
- [ ] 4. Stealth watch (log-mined watchlist, liveness probes, 429 `alternates` discovery)
- [ ] 5. Parked: local model scan/load — SimSense explicitly out of scope

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

1. Stage 3: transition alerts (model dies / comes back) and actions — copy slug, set a new
   main model via `hermes config set model.default`, hint for switching the current
   session with `/model`.

## Open questions

- Probe cadence default for stealth watches (manual + 15 min proposed).
- Whether session-scoped switching may rely on the user running `/model` (fallback if no
  gateway route exists).
