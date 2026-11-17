# 11. One deployment per hospital

Date: 2026-11-17

## Status

Accepted

## Context

The app is built first as a public demo and then, perhaps, for one hospital ward at a time. Each
hospital is its own data controller, with its own data protection officer, its own retention rules
and possibly its own wish to run the system on its own servers.

A hospital is not one place with one set of rules. It can have more than one site or unit with its
own timezone, shifts, note format and units, so the app already keeps those per **facility**: a
row in the `facility` table that the admin edits. The demo database holds two facilities, one in
the Philippines and one in the United States.

The open question was how to hold more than one hospital:

- **Shared database, tenant column (row-level multi-tenancy).** Every table gains a `tenant_id`,
  every query filters on it, and Postgres row-level security backs the filter up. One deployment
  serves every hospital.
- **One deployment and one database per hospital (single-tenant).** Each hospital gets its own
  stack: its own database, its own functions, its own secrets and its own address. Inside it,
  `facility` rows separate the hospital's sites.

Two facts weigh most. Clinical records here are locked at the database level: a signed note's
version can never be updated or deleted, and a planned hash-chained audit log follows the same
rule. A tenant column added to those tables later would mean rewriting rows that the triggers
exist to protect, and every hash in the chain would cover it. And a mistake in a tenant filter is
the worst kind of bug for this app: one hospital's patient notes shown to another hospital's nurse.

## Decision

**One deployment and one database per hospital.** There is no tenant id and no row-level
multi-tenancy. A hospital with several sites or units has several `facility` rows in its own
database; facilities share that hospital's staff list, its one admin account and its AI budget.

- The live Terraform root takes the environment's name (`environment`), which names every
  resource and secret path, so a second hospital is a second set of variables and state, not new
  code.
- Nothing in the code asks which country or which hospital it serves: everything regional comes
  from the facility row.
- The public demo is one such deployment, with synthetic data only.

## Consequences

- **Isolation is physical.** One hospital's data never shares a database, a role or a secret with
  another's, which is the simplest answer for a data protection officer and the same shape as
  running on a hospital's own servers.
- **The locked tables stay as they are.** No migration ever has to add a tenant column to signed
  notes or the audit chain.
- **No tenant filter to get wrong.** A query can't leak across hospitals, because there is only
  one hospital in each database.
- **Cost grows per hospital.** Each deployment pays for its own database (scale-to-zero keeps an
  idle one cheap) and its own small fixed costs, where a shared deployment would pay once.
- **Upgrades run once per deployment.** Migrations and deploys repeat for every hospital, so the
  deploy is one script with the environment as its argument, run the same way each time.
- **No cross-hospital view.** Comparing hospitals, if anyone ever needs it, means exporting from
  each one; nothing in the app reads across deployments.
