# Project Status — Nous Free Models

Last updated: 2026-11-13

Current stage: **1 complete, starting 2**

## Roadmap

- [x] 0. Safety net — git repo, status file, `.gitignore`
- [x] 1. Theme follow (Hermes skin engine) + manual override picker
- [ ] 2. Config vs available comparison (default, aux pins, fallback chain, actual usage)
- [ ] 3. Alerts + model actions (death notices, set main model, copy slug, session hint)
- [ ] 4. Stealth watch (log-mined watchlist, liveness probes, 429 `alternates` discovery)
- [ ] 5. Parked: local model scan/load — SimSense explicitly out of scope

## Decisions

- Cloud-only for this app; no local model loading for now.
- Themes: live-follow the installed Hermes skin engine, with an `Auto (follow Hermes)`
  mode plus a manual per-skin override. Polling interval ~3 s.
- Work proceeds in git-committed stages so any stage can be reverted independently.
- GitHub push is deferred until the token is handed over via `%USERPROFILE%\.github-pat`
  (never pasted in chat, never committed).

## Next steps

1. Stage 2: read configured models (`model.default`, `auxiliary.*`, `fallback_providers`)
   via `hermes config get`, compare against the live free union, flag dead/paid,
   and show observed per-turn usage from `logs/agent.log`.

## Open questions

- Exact GitHub repo name/URL for the eventual push.
- Probe cadence default for stealth watches (manual + 15 min proposed).
