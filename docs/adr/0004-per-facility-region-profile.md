# 4. A per-facility region profile

Date: 2026-11-13

## Status

Accepted

## Context

The app is tested on Philippine wards and on US units. The two differ in ways that reach the data,
not just the screen:

- **Shifts.** Philippine wards often work three 8-hour shifts (6-2, 2-10, 10-6); US units mostly
  work two 12-hour shifts (7a-7p, 7p-7a). A US night shift lasts 11 or 13 hours on the nights the
  clocks change, because Pacific time has daylight saving time and Manila doesn't.
- **Units.** Philippine notes write temperatures in °C and weights in kg; US notes write °F and
  often lb, and patient weights should be metric (ISMP).
- **Words and formats.** "Ward" and "unit", "endorsement" and "handoff", "hospital no." and "MRN".
  Focus charting is called FDAR in the Philippines and DAR in the US, with the same four parts.

Some of these values end up inside signed, hashed records, so they can't be decided later without
migrating records that the database refuses to change.

## Decision

Each facility row holds a region profile: IANA timezone, locale, the time the nursing day starts,
the list of shifts (code, label, start and end as local clock times, ink colour), the note formats
and the default one, a default unit per measure (UCUM codes: temperature, weight, volume) and the
clock (24-hour by default).

- **Presets are templates.** `preset("PH", …)` and `preset("US", …)` fill a new row; after that the
  row is the truth, and an admin edits it. No code path asks which country a facility is in, and a
  repository test refuses timezone names outside the presets, demo data, tests and docs.
- **One validation for presets and edits:** the shifts must cover 24 hours with no gap or overlap,
  the nursing day must start at a shift's start, and the timezone must be a real IANA zone.
- **Shift maths uses local clock times.** A shift edge is a local wall-clock time in the facility's
  zone, converted to UTC, never "start + 12 hours". Shifts are half-open, `[start, end)`.
- **A shift is dated by the nursing day it starts in.** The nursing day starts at the facility's
  `day_starts_at`; a ward that dates its night shift by the next day sets it to the night shift's
  start, and any time from noon on names the next calendar day.
- **The session picks the shift, not the clock.** At 14:10 the nurse finishing the 6-2 and the
  nurse starting the 2-10 share a clock time, so sign-in only suggests a shift: the one in progress,
  or the next one when it starts within 30 minutes. The nurse can switch to the previous, current
  or next shift.
- **Each note keeps a snapshot of its shift**: code, label, start and end in UTC, the nursing date
  and the timezone. Editing the profile never rewrites a written note.
- **The code never converts units.** A number in a draft must match its source, and a unit next to
  it must match the unit the nurse wrote, or the facility's default when she wrote none. US weight
  has no default, so a weight unit the nurse didn't write is always flagged.
- **What is frozen now:** anything written into a note, its hash or an immutable row (the shift
  snapshot, the format and section codes, numbers and units as typed, UCUM codes in structured
  values, region-neutral identity fields). Settings that only affect display or sessions can be
  added later as additive changes.

`tzdata` is a locked dependency, so the zones exist where the operating system has no copy (slim
and Lambda images) and update through Dependabot. Where the system does have a copy, Python reads
it first, so a developer PC can run newer or older rules than the Lambda image; the DST tests pin
the dates that matter.

## Consequences

- The demo database holds two facilities, one Philippine and one US. That is the test that no
  region is hidden in the code.
- Shift and date logic is in one tested module, with the DST nights and the midnight crossing pinned
  by tests.
- An admin can change shift times or units without touching any note already written.
- A hospital with both 8-hour and 12-hour units needs a ward-level shift override later; it is an
  additive change.

## Alternatives considered

- **A country switch in code** (`if region == "PH"`). It is quick, but every new facility type
  becomes a code change, and the second region would show where the first was assumed.
- **Shift by clock time alone.** It can't tell the outgoing and incoming nurse apart at handover,
  and it would put late charting in the wrong shift.
- **Store notes with the facility's current settings instead of a snapshot.** An admin edit would
  then rewrite the meaning of signed records.
