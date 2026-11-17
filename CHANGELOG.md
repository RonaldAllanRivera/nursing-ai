# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Commit messages follow
[Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/).

## [Unreleased]

## [0.2.0] - 2026-11-17

### Added

- The core draft pipeline, which turns a rough note into an FDAR draft and checks every line
  against the nurse's words. Known names and identifiers become tokens before any AI call, and the
  call stops if one survives. Each quoted phrase must appear in the note character for character,
  never inside a longer word or number. Lines whose quotes, numbers, doses or units don't match
  the note are flagged. A missing-items list names what the chart expects but the shift's notes
  don't mention. Fake, replay and Anthropic providers come with the first FDAR prompt, the pipeline
  reproduces all three demo drafts and checklists exactly, and a decision record explains why it
  uses structured output instead of the Citations API.
- The web app, built against a mock API (MSW) that answers from the synthetic demo cases. Sign in
  as a demo persona, pick a patient, write a rough note (saved once even when the request is
  retried) and follow the draft's progress. In the trace view, tapping a
  draft line lights up its source words in the note and marks a differing number; each line can be
  confirmed, edited, removed or put back, and the note signed (it locks and shows its hash) or
  discarded. An admin edits a facility's timezone, locale, shifts, units and clock, and every
  screen shows dates, times and ward words from those settings. Error, not-found and loading
  screens are included. Fonts: Atkinson Hyperlegible Next and Mono, under the SIL Open Font
  License 1.1.
- The API and database behind those screens. Postgres tables come with a first migration, and
  the database itself refuses to change or delete a signed note version or a facility's settings
  history, and locks a note once it is signed. Demo personas sign in to a session that starts on
  the nearest shift. A rough note is saved once per `Idempotency-Key` in the session's shift and
  drafted in the background by the core pipeline (mock, replay, or live behind the monthly AI
  cap). Each draft line can be confirmed, edited, removed or put back, and the note then signed
  into a hashed record or discarded; every change sends the note's `ETag` back as `If-Match`. The
  admin edits each facility's settings and every save is kept; only nurses write and sign notes.
  Errors are RFC 9457 problems, and the JSON logs keep an allowlist of fields, so note text, names
  and keys never reach them. A synthetic seed fills both demo facilities, and a mock hospital
  record importer checks each patient's chart before saving it.
- `make migrate` and `make seed`, and `make up` runs both before the API starts. `make spend` now
  adds this month's AI spend from the usage table.
- `make e2e-mock`, which runs the Playwright journeys (three screen widths, a keyboard path and axe
  accessibility checks) against the mock API with no database or API container. CI runs it after
  the web checks.
- Replay mode with real drafts. `make record-replays` asks the live model once for each of the three
  demo notes and saves its answers, so replay mode, the end-to-end journeys and CI show real drafts
  at no cost. It refuses unless live mode, the key and the monthly cap are all set, checks the cap
  before every call, never retries a billed call, and skips a note that is already recorded. The
  three recordings are committed; recording them cost about $0.07.
- End-to-end journeys against the real stack (Postgres, the API and the web app): write a note,
  check every draft line, edit one, sign and see it locked, at three screen widths, by keyboard
  alone, for the US facility and as the admin, with axe accessibility checks. `make e2e
  AI_MODE=replay` runs them on the recorded drafts, and so does CI.
- The database also refuses a record for a note that isn't signed, reopening a discarded draft and
  changing a rough note (migration 0002).
- README: a short demo GIF, screenshots and a "What works today" list; `make readme-media` makes
  them from the real stack in replay mode.
- The Terraform for the live demo on AWS in Sydney. Every module is tested against a mocked AWS
  provider, and nothing has been applied yet. It covers a private dual-stack network whose only way
  out is an IPv6 egress-only gateway, and Aurora Serverless v2 PostgreSQL 17 that pauses after 5
  idle minutes, with a password that never reaches the Terraform state. One container image runs
  as two Lambdas: the API behind a throttled HTTP API, and a queue worker with a dead-letter queue,
  each reading only its own secrets. The web app is served from a private S3 bucket behind
  CloudFront, with alarms for API errors, dead jobs and AI spend, and a budget brake that denies
  the app's Lambdas everything at 100% of the budget. A bootstrap stack adds the locked state
  bucket and GitHub OIDC roles behind a switch. One script formats, validates, tests, lints and
  scans it all; `make infra-check` runs it locally, and CI runs it on every change to the
  Terraform. Decision records 5 to 8 explain the hosting choices, and the infra guide covers setup
  and a monthly cost table.

### Changed

- The line checks flag more, each at the cost of one confirm when the draft was right: a litre
  amount; a rate the note writes after a bare number; per week, month and shift; long spelled-out
  rates; a concentration such as g/dL against g/L; a line break inside a rate; a dose frequency or
  duration the nurse didn't write (daily, BID, weekly, every 2 hours); a dose unit the nurse never
  wrote; and a vital sign or intake/output value swapped between labels, even when the draft spells
  the label out ("HR" as "heart rate"). "5 units / HR 88", a heart rate written after a dose, is
  flagged both ways instead of being read as per hour.
- A "Source found" line now says that code checked the quoted words and numbers, not the meaning.
- `make spend` counts billed calls apart from the free mock and replay ones.
- Settings names the note format "DAR" for a US facility.
- CI runs once, not twice, for a branch with an open pull request.
- Version 0.2.0 across the packages and the API.
- README: the planned AWS design moves to Sydney (`ap-southeast-2`), with Aurora Serverless v2
  and auto-pause instead of RDS, SSM Parameter Store instead of Secrets Manager, and an IPv6
  egress-only internet gateway instead of NAT. Getting started adds mock mode and `make e2e-mock`,
  and the web stack lists what is built, with the PWA marked as planned.

### Fixed

- A billed AI answer that fails (refused, cut off, or not the draft's shape) now counts against
  the monthly cap, and a call that times out is no longer retried, so it can't be billed twice.
- Logging no longer breaks on unusual records, and a logging error never prints a record's values.
- The dev server reaches the API by its address, so a failed `localhost` lookup can't break it.
- The mock API refuses a write in the same order as the real API.
- A room label such as "412-A" stays on one line inside its bed tab.

### Security

- The public-history and staged checks catch a private word in a file, or a file name, that isn't
  UTF-8, without printing any part of it; gitleaks ignores git replace refs; `make private-words`
  refuses a symlinked word list, saves it atomically and asks git before trusting a folder.

## [0.1.0] - 2026-11-13

### Added

- A uv workspace monorepo with the shared core and the api, mcp and evals entry points, plus the
  web app, infra and docs folders.
- The health endpoint and the start page that shows it.
- Postgres and the API in Docker Compose, with make targets.
- End-to-end tests at three screen widths.
- CI on GitHub Actions, with Dependabot.
- Pre-commit hooks, and a pre-push hook that runs the public-history check.
- The public-history check, which scans the whole git history (file changes, commit and tag
  messages, authors, file and tag names) for secrets, stray paths and private words.
- The first architecture decision records.
- README with the problem, the safety approach (the model writes, code checks, the nurse signs),
  a planned architecture, the evaluation metrics and the roadmap.
- This changelog.

### Changed

- README roadmap: the MCP server and tool-using agent, with the hash-chained audit log and a draft
  SBAR handoff, now come before the full ward app, as v0.5; the full ward moves to v0.6; v0.4 adds a
  planned glossary lookup for ward shorthand and Taglish terms (hybrid search with pgvector).
- README: the gold set is described as synthetic and AI-reviewed, with nurse review pending, and the
  missing-items checklist and its example follow the planned checklist rules.
- README: the project is now called Sourceline, with "Nursing Documentation AI" as the subtitle
  and the tagline "Every line has a source". The repository and package names don't change.

<!--
Template for each release (newest on top):

## [0.1.0] - YYYY-MM-DD

### Added      new features
### Changed    changes to existing behaviour
### Deprecated features that will be removed
### Removed    features removed in this release
### Fixed      bug fixes
### Security   vulnerability fixes and hardening

Link references go at the bottom once the repository has a remote, for example:
[Unreleased]: https://github.com/<owner>/<repo>/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/<owner>/<repo>/releases/tag/v0.1.0
-->
