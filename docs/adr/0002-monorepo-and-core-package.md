# 2. A monorepo with one shared core package

Date: 2026-11-13

## Status

Accepted

## Context

The product has several ways in: an HTTP API for the web app, a Model Context Protocol (MCP) server
for agent tools, and an evaluation harness that runs the same drafting pipeline against a gold set.
All of them need the same domain model, the same database layer and the same safety checks. If each
kept its own copy, a fix to a safety check could reach one entry point and miss another.

The project also has a web app, infrastructure code and documentation that change together with the
Python code, and it is built by one person with tests that span all of them.

A top-level Python package named `mcp` would also shadow the official MCP Python SDK, which is
imported as `mcp`.

## Decision

We use one Git repository with a uv workspace.

- `core/` holds the domain model, the draft pipeline, de-identification, providers and the database
  layer. It is the only place with business logic.
- `api/`, `mcp/` and `evals/` are thin entry points that depend on `core` and add only
  transport, wiring and reporting.
- `web/` (React + TypeScript), `infra/` (Terraform) and `docs/` (architecture notes and ADRs) sit
  alongside them in the same repository.
- The workspace root is virtual: it has no package of its own and only pins the shared tooling and
  one lock file.
- Import names are prefixed: `nursing_core`, `nursing_api`, `nursing_mcp` and `nursing_evals`
  (distributions `nursing-core` and so on), in a `src` layout. The folders keep their short
  names. The prefix keeps the `mcp` name free for the official SDK and does not depend on the
  product's display name.

## Consequences

- One change can touch the core, an entry point, the web app and a test, and ships as one commit
  that CI checks as a whole.
- One lock file and one set of tool versions apply to every Python package.
- The entry points stay small, so behaviour is tested once, in `core`.
- Package imports are a little longer than bare names.
- The repository grows over time and every contributor gets all of it. This is acceptable for a
  project of this size.

### Alternatives considered

- **Separate repositories** for the API, the MCP server, the evaluations and the web app. This gives
  independent release cycles, which we do not need, at the cost of publishing `core` as a package
  and coordinating versions across repositories for every change.
- **One Python package** with the API, MCP server and evaluations as modules inside it. It is
  simpler to set up, but nothing stops an entry point from reaching into another's internals, and
  every deployment would carry the dependencies of all of them.
