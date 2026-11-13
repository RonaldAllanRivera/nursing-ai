# 1. Record architecture decisions

Date: 2026-11-13

## Status

Accepted

## Context

This project will make decisions that are hard to see from the code alone: which libraries to use,
how the packages fit together, what is checked by code and what by a person. People who join later,
and the author a few months from now, need to know what was decided and why, not just what the
code does.

## Decision

We record each significant architectural decision as an Architecture Decision Record (ADR), using
the format described by Michael Nygard: a title, a date, a status, the context, the decision and
the consequences.

- ADRs live in `docs/adr/`, one Markdown file each, named `NNNN-short-title.md` with a
  four-digit number that is never reused.
- A decision that is later replaced is not edited away. Its status changes to "Superseded by
  NNNN", and the new ADR explains the change.
- Statuses are Proposed, Accepted, Deprecated and Superseded.

## Consequences

- The reasons behind a choice stay next to the code and go through review like any other change.
- Writing a short ADR takes a little time, so we write one only for decisions that are costly to
  reverse or that a newcomer would otherwise ask about.
- The history of the project's thinking, including rejected options, is easy to read in order.
