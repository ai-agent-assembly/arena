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

## Docs/website integration contract

This section is for whoever wires up `official-website`'s `/arena` page or
this repo's own `docs/latest-reports.md` (AAASM-4429) to actually consume
live report data, rather than the placeholder/static content each has today.
It builds on the "Stable, consumer-facing files" / "Internal / not
guaranteed" split above — that split (`latest.json`, `latest.md`,
`leaderboard.json`, per-match `arena-report.{json,md}` vs. `audit.jsonl`) is
the full list of what's safe to depend on; this section covers *how* and
*where* a consumer outside this repo actually reaches those files, and which
of the two downstream consumers should show what.

### Where these files are reachable from outside this repo

Locally (and on `main` after every `scheduled-matches.yml` run), the files
live at repo-root-relative paths: `reports/latest.json`,
`reports/leaderboard.json`, `reports/matches/<match-id>/arena-report.json`,
etc. — exactly the layout above. Be honest about what "reachable" means
today, though:

- **What actually resolves right now:** raw GitHub content, e.g.
  `https://raw.githubusercontent.com/ai-agent-assembly/arena/main/reports/latest.json`
  (and the equivalent for `leaderboard.json` / any
  `matches/<match-id>/arena-report.json`) — a plain, unauthenticated HTTP
  GET that always reflects whatever `scheduled-matches.yml` (AAASM-4428)
  last committed to `main`. The GitHub Contents API is the equivalent
  option for a consumer that wants commit metadata alongside the file.
- **What does *not* resolve yet:** there is no `docs.agent-assembly.com/arena/reports/...`
  URL. `mkdocs.yml`'s `site_url: https://docs.agent-assembly.com/arena/`
  (this repo's own docs site, aggregated into the docs hub per the
  AAASM-4413/4414 `mike`/gh-pages-clone strategy referenced in
  `mkdocs.yml`'s `plugins.mike` comment) only serves what lives under
  `docs/` — MkDocs has no route into a repo-root `reports/` directory, and
  nothing currently copies `reports/*.json` into `docs/` at build time.
  `docs/report-schema.md`'s two sample reports
  (`docs/samples/winning-match/`, `docs/samples/losing-match/`) are
  checked-in static fixtures generated by `scripts/generate_report_samples.py`
  for illustration — they are not the live `reports/` data and don't change
  when a real match runs.
- **What closes that gap:** AAASM-4429 (sibling ticket to this one, not
  implemented here) adds a `docs/latest-reports.md` page to this repo's
  MkDocs site that's expected to render the live contract documented in
  this file. Once it lands, the docs site becomes the first consumer
  properly wired into MkDocs' own URL space rather than reaching past it to
  raw GitHub content. Until then, raw GitHub content (or the Contents API)
  is the only real integration point for an external consumer.

### Website vs. docs: who shows what

`official-website`'s `/arena` page (`src/pages/arena.tsx`, added by
AAASM-4407) currently ships a **static placeholder**, not a live-wired
teaser — confirmed by reading the file directly
(`src/pages/arena.tsx:53-65` as of commit `caeb911` on branch
`v0.0.0/AAASM-4407/website_arena_showcase`): a hardcoded "Latest report"
card with fixed copy ("Match reports are published as trials run in Arena.
Check the repository for the latest results across scenarios and
frameworks.") and a link straight to the GitHub repo. It does not fetch
`reports/latest.json` or `reports/leaderboard.json` today.

When that card is eventually wired up for real, it should stay a
**lightweight summary/teaser only** — e.g. the latest match's
`report.score.outcome`, `scenario_id`, and `generated_at` from
`latest.json`'s small top-level fields, plus a link out to the full report —
not the full inlined `MatchReport`. `official-website`'s own
`.claude/CLAUDE.md` scopes that repo to "marketing content only... link
out, don't duplicate," which matches this split: the **full technical
detail** (per-trial results, audit events, victory conditions) belongs on
`docs.agent-assembly.com/arena`, not on the marketing site. Once
AAASM-4429's `docs/latest-reports.md` lands, that page — not
`official-website` — is the canonical place a reader goes to see a complete
report rendered.

### Publishing phases: MVP vs. future

- **MVP (current, actual mechanism):** static JSON/Markdown files checked
  into this repo's `reports/` directory, refreshed by
  `scheduled-matches.yml` CI (AAASM-4428) via `refresh_static_index`
  (AAASM-4397) after `generate_report` (AAASM-4390/4391) runs a match. No
  API, no database, no object storage — a consumer fetches a file over
  plain HTTP (today, raw GitHub content) and reads it. That's the entire
  mechanism.
- **Future (a possible direction, not planned/committed work):** a live API
  or object-storage-backed publishing path (e.g. syncing `reports/` to a
  CDN bucket, or exposing a small read API) could remove the
  raw-GitHub-content dependency described above. This is explicitly
  out of scope for AAASM-4396's Story and isn't scheduled — noted here only
  so a future ticket doesn't have to rediscover that the MVP intentionally
  stopped at "files checked into git."
