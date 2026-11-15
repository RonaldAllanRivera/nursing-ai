# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Commit messages follow
[Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/).

## [Unreleased]

### Added

- The core draft pipeline, which turns a rough note into an FDAR draft and checks every line
  against the nurse's words. Known names and identifiers become tokens before any AI call, and the
  call stops if one survives. Each quoted phrase must appear in the note character for character,
  never inside a longer word or number. Lines whose quotes, numbers, doses or units don't match
  the note are flagged. A missing-items list names what the chart expects but the shift's notes
  don't mention. Fake, replay and Anthropic providers come with the first FDAR prompt, the pipeline
  reproduces all three demo drafts and checklists exactly, and a decision record explains why it
  uses structured output instead of the Citations API.
- The web app, built against a mock API (MSW) that answers from the synthetic demo cases; the real
  endpoints come next. Sign in as a demo persona, pick a patient, write a rough note (saved once
  even when the request is retried) and follow the draft's progress. In the trace view, tapping a
  draft line lights up its source words in the note and marks a differing number; each line can be
  confirmed, edited, removed or put back, and the note signed (it locks and shows its hash) or
  discarded. An admin edits a facility's timezone, locale, shifts, units and clock, and every
  screen shows dates, times and ward words from those settings. Error, not-found and loading
  screens are included. Fonts: Atkinson Hyperlegible Next and Mono, under the SIL Open Font
  License 1.1.
- `make e2e-mock`, which runs the Playwright journeys (three screen widths, a keyboard path and axe
  accessibility checks) against the mock API with no database or API container. CI runs it after
  the web checks.

### Changed

- README: the planned AWS design moves to Sydney (`ap-southeast-2`), with Aurora Serverless v2
  and auto-pause instead of RDS, SSM Parameter Store instead of Secrets Manager, and an IPv6
  egress-only internet gateway instead of NAT. Getting started adds mock mode and `make e2e-mock`,
  and the web stack lists what is built, with the PWA marked as planned.

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
