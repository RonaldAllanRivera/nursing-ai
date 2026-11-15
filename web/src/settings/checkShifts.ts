import { formatLocalTime } from "../region/format";

/** What the whole-table rules need of a shift: its code and its times as "HH:MM". */
export interface ShiftTimes {
  code: string;
  starts_local: string;
  ends_local: string;
}

type Clock = "24h" | "12h";

const DAY_MINUTES = 24 * 60;

function minutesOf(time: string): number | null {
  const found = /^(\d{2}):(\d{2})/.exec(time);
  if (!found) return null;
  const hours = Number(found[1]);
  const minutes = Number(found[2]);
  return hours < 24 && minutes < 60 ? hours * 60 + minutes : null;
}

/** A minute of the day as the facility's clock words it. */
function wording(minutes: number, clock: Clock): string {
  const wrapped = ((minutes % DAY_MINUTES) + DAY_MINUTES) % DAY_MINUTES;
  const pad = (n: number) => String(n).padStart(2, "0");
  return formatLocalTime(`${pad(Math.floor(wrapped / 60))}:${pad(wrapped % 60)}`, clock);
}

/** Minutes from `from` forward to `to` on a 24-hour clock (0 when they are the same time). */
function forward(from: number, to: number): number {
  return (((to - from) % DAY_MINUTES) + DAY_MINUTES) % DAY_MINUTES;
}

const GENERAL = "Together the shifts must cover 24 hours with no gap or overlap.";

/**
 * The whole-table rules, in plain English, with times worded in the facility's clock. They are
 * the server's rules (the facility's `_shifts_tile_the_day` and `_has_a_length`): a shift ends at
 * a different time than it starts, codes are unique, sorted by start each shift ends where the
 * next starts (the last where the first starts, past midnight), so the shifts cover 24 hours
 * with no gap or overlap, and the nursing day starts when one of the shifts starts. A shift
 * whose times are not filled in yet is the field's own problem and is left out here. When one
 * shift spans another, the specific words would mislead, so the general line is given instead.
 * An empty list means the table is fine.
 */
export function checkShifts(
  shifts: readonly ShiftTimes[],
  dayStartsAt: string,
  clock: Clock,
): string[] {
  const problems: string[] = [];
  if (shifts.length === 0) return ["Add at least one shift."];

  const seen = new Set<string>();
  const repeated = new Set<string>();
  for (const { code } of shifts) {
    const name = code.trim();
    if (name === "") continue;
    if (seen.has(name) && !repeated.has(name)) {
      repeated.add(name);
      problems.push(`Two shifts use the code ${name}. Give each shift its own code.`);
    }
    seen.add(name);
  }

  const timed = shifts.flatMap((shift) => {
    const start = minutesOf(shift.starts_local);
    const end = minutesOf(shift.ends_local);
    return start === null || end === null ? [] : [{ code: shift.code.trim(), start, end }];
  });

  const usable = timed.filter((shift) => {
    if (shift.start !== shift.end) return true;
    problems.push(`The ${shift.code} shift ends when it starts. Give it a different end time.`);
    return false;
  });

  const covers = (shift: (typeof usable)[number], minute: number) =>
    forward(shift.start, minute) < forward(shift.start, shift.end);

  let muddled = false;
  const ordered = [...usable].sort((a, b) => a.start - b.start);
  for (const [at, current] of ordered.entries()) {
    const following = ordered[(at + 1) % ordered.length];
    if (!following) continue;
    const length = forward(current.start, current.end);
    // Between the two starts. A lone shift is followed by itself, a whole day later.
    const between = ordered.length === 1 ? DAY_MINUTES : forward(current.start, following.start);
    if (length < between) {
      // A real gap only if no other shift is already working at the minute the gap starts.
      if (usable.some((other) => other !== current && covers(other, current.end))) muddled = true;
      else {
        problems.push(
          `There's a gap between ${wording(current.end, clock)} and ${wording(following.start, clock)}.`,
        );
      }
    } else if (length > between) {
      // The next shift must run on past the end of this one; if it sits inside it, one shift spans another.
      if (forward(current.start, following.end) > length) {
        problems.push(
          `The ${current.code} and ${following.code} shifts overlap from ${wording(following.start, clock)} to ${wording(current.end, clock)}.`,
        );
      } else muddled = true;
    }
  }
  if (muddled) problems.push(GENERAL);

  const day = minutesOf(dayStartsAt);
  const starts = timed.map((shift) => shift.start);
  if (day !== null && starts.length > 0 && !starts.includes(day)) {
    problems.push("The nursing day must start when one of the shifts starts.");
  }
  return [...new Set(problems)];
}
