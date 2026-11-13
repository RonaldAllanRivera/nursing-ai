# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Commit messages follow
[Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/).

## [Unreleased]

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
