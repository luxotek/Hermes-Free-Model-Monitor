# Project Status — Nous Free Models

Last updated: 2026-11-14

Current stage: **2 complete, starting 3**

## Roadmap

- [x] 0. Safety net — git repo, status file, `.gitignore`
- [x] 1. Theme follow (Hermes skin engine) + manual override picker
- [x] 2. Config vs available comparison (default, aux pins, fallback chain, actual usage)
- [ ] 3. Alerts + model actions (death notices, set main model, copy slug, session hint)
- [ ] 4. Stealth watch (log-mined watchlist, liveness probes, 429 `alternates` discovery)
- [ ] 5. Parked: local model scan/load — SimSense explicitly out of scope

## Decisions

- Cloud-only for this app; no local model loading for now.
- Themes: live-follow the installed Hermes skin engine, with an `Auto (follow Hermes)`
  mode plus a manual per-skin override. Polling interval ~3 s. Manual picks persist in
  `theme_choice.json` (gitignored).
- Work proceeds in git-committed stages so any stage can be reverted independently.
- GitHub push is deferred until the token is handed over via `%USERPROFILE%\.github-pat`
  (never pasted in chat, never committed). Repo appears to be `luxotek/herms-free-mode`.
- Config reading uses `hermes config get <key>` (never hand-edits config.yaml).
- Stage 2 finding: `fallback #2` (`reflection/beam-1.0-501b-a23b:free`) is listed but no
  longer free — classified PAID, shown color-coded.

## Next steps

1. Stage 3: transition alerts (model dies / comes back) and actions — copy slug, set a new
   main model via `hermes config set model.default`, hint for switching the current
   session with `/model`.

## Open questions

- Exact GitHub repo name/URL for the eventual push (Firefox showed `luxotek/herms-free-mode`).
- Probe cadence default for stealth watches (manual + 15 min proposed).
- Whether session-scoped switching may rely on the user running `/model` (fallback if no
  gateway route exists).
