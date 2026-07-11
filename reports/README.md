# `reports/` — static report artifact layout

This directory is where `aasm-arena run` writes every match's durable report
artifacts (`--reports-root`, default `reports/matches/`), plus a small set
of top-level "static index" files a website or docs site can fetch directly
— no Arena installation, no backend service, just a plain HTTP GET against
whatever hosts this directory (or a copy of it, e.g. a CI artifact / GitHub
Pages / object storage bucket).

Everything under `reports/` other than this `README.md` is **generated
output**, written by `aasm-arena run` — not hand-authored. This file exists
to document the shape of that generated output so a consumer doesn't have to
read Arena's source to know what to expect.

Unlike most generated output, it is **tracked in git**: the
`scheduled-matches` GitHub Actions workflow
(`.github/workflows/scheduled-matches.yml`, AAASM-4428) runs real matches on
a schedule (and on manual `workflow_dispatch`) and commits the refreshed
`latest.json`/`latest.md`/`leaderboard.json`/`matches/` back to `main`, so
`reports/` on `main` always reflects a real, recent match history a
docs/website consumer can fetch directly — no CI artifact download, no
backend service, no Arena installation required. See `.gitignore` for the
(deliberately absent) ignore rule.

## Layout

```
reports/
├── README.md          # this file (checked in)
├── latest.json         # generated — most recent match, full report inlined
├── latest.md            # generated — Markdown rendering of the same match
├── leaderboard.json      # generated — one summary row per known match
└── matches/
    └── <match-id>/
        ├── arena-report.md      # generated — human-readable match report
        ├── arena-report.json     # generated — machine-readable match report
        └── audit.jsonl            # generated — the match's redacted audit trail
```

## Stable, consumer-facing files

These paths and shapes are the contract a website/docs consumer can depend
on. Each carries its own `schema_version` field — check it before assuming a
field exists, and expect it to change only as a deliberate, visible schema
bump (see `arena.reports.models.SCHEMA_VERSION` and
`arena.reports.index.LATEST_INDEX_SCHEMA_VERSION`/
`LEADERBOARD_SCHEMA_VERSION`).

- **`reports/latest.json`** — the most recently generated match, in full.
  Read this for "what's the current state of the arena." Shape
  (`arena.reports.index.LatestReportIndex`):

  ```json
  {
    "schema_version": "1",
    "match_id": "<the most recent match's id>",
    "path": "matches/<match-id>/arena-report.json",
    "generated_at": "<when this file was written, ISO 8601 UTC>",
    "report": { /* the full MatchReport — same shape as that match's own arena-report.json */ }
  }
  ```

  The full report is inlined (not just referenced by `path`) so a static
  site can fetch this one URL and render a complete result without a second
  request. `path` is still included for consumers that want the per-match
  directory's other files (`arena-report.md`, `audit.jsonl`) too.

- **`reports/latest.md`** — the same most-recent match, rendered as
  Markdown (`arena.reports.markdown.render_markdown`) — identical content to
  that match's own `matches/<match-id>/arena-report.md`. Useful for a docs
  page that wants to embed the latest result directly as prose/tables rather
  than parse JSON.

- **`reports/leaderboard.json`** — one summary row per match found under
  `matches/`, most recent first. Deliberately a lightweight, on-demand
  summary — not a persistent match-history database — rebuilt from whatever
  `matches/*/arena-report.json` files exist on disk at refresh time. Shape
  (`arena.reports.index.LeaderboardIndex`):

  ```json
  {
    "schema_version": "1",
    "generated_at": "<when this file was written, ISO 8601 UTC>",
    "matches": [
      {
        "match_id": "...",
        "scenario_id": "...",
        "outcome": "agent-assembly wins",
        "critical_escapes": 0,
        "generated_at": "<that match's own start time, ISO 8601 UTC>"
      }
    ]
  }
  ```

  An empty `"matches": []` is a valid, expected state (no matches run yet),
  not an error.

- **`reports/matches/<match-id>/arena-report.json`** — the full
  `MatchReport` for one match (`arena.reports.models.MatchReport`,
  `schema_version` field per `arena.reports.models.SCHEMA_VERSION`). Every
  match ever run keeps its own directory here — `latest.json`/
  `leaderboard.json` are rolling pointers on top of this history, they never
  overwrite or collapse it.

- **`reports/matches/<match-id>/arena-report.md`** — the same match,
  rendered as Markdown.

## Internal / not guaranteed

- **`reports/matches/<match-id>/audit.jsonl`** — the match's raw
  (already-redacted) audit trail, one JSON object per line
  (`arena.integrations.audit.ArenaAuditEvent`). Useful for debugging a
  specific match in depth, but not part of the versioned report schema
  above — treat its shape as an implementation detail of
  `arena.integrations.audit`, not a stable public contract.

## How this directory gets (re)generated

`aasm-arena run <scenario-id>` writes a new `matches/<match-id>/` directory
(`arena.reports.generate.generate_report`) and then refreshes `latest.json`,
`latest.md`, and `leaderboard.json` (`arena.reports.index.
refresh_static_index`) from whatever's on disk under `matches/` at that
point — so the static index is always consistent with the full match
history, not just the match that was just run.

`refresh_static_index` is also callable standalone (it takes only the
`matches/` root path) to rebuild the index without running a match — e.g.
after manually adding/removing a `matches/<match-id>/` directory.

In CI, `.github/workflows/scheduled-matches.yml` runs `aasm-arena run
github-maintainer-dungeon --agent <id>` once per official agent (daily, plus
on-demand via `workflow_dispatch`) and commits whatever changed under
`reports/` back to `main` with a `github-actions[bot]` commit — see that
workflow file for exactly which agents run and how it avoids re-triggering
`ci.yml`/`documentation.yml` on its own commit.
