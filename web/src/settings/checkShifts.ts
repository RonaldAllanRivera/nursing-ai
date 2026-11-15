/** What the whole-table rules need of a shift: its code and its times as "HH:MM". */
export interface ShiftTimes {
  code: string;
  starts_local: string;
  ends_local: string;
}

const DAY_MINUTES = 24 * 60;

function minutesOf(time: string): number | null {
  const found = /^(\d{2}):(\d{2})/.exec(time);
  if (!found) return null;
  const hours = Number(found[1]);
  const minutes = Number(found[2]);
  return hours < 24 && minutes < 60 ? hours * 60 + minutes : null;
}

function clock(minutes: number): string {
  const wrapped = ((minutes % DAY_MINUTES) + DAY_MINUTES) % DAY_MINUTES;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(Math.floor(wrapped / 60))}:${pad(wrapped % 60)}`;
}

/** Minutes from `from` forward to `to` on a 24-hour clock (0 when they are the same time). */
function forward(from: number, to: number): number {
  return (((to - from) % DAY_MINUTES) + DAY_MINUTES) % DAY_MINUTES;
}

/**
 * The whole-table rules, in plain English. They are the server's rules (the facility's
 * `_shifts_tile_the_day` and `_has_a_length`): a shift ends at a different time than it starts,
 * codes are unique, sorted by start each shift ends where the next starts (the last where the
 * first starts, past midnight), so the shifts cover 24 hours with no gap or overlap, and the
 * nursing day starts when one of the shifts starts. A shift whose times are not filled in yet is
 * the field's own problem and is left out here. An empty list means the table is fine.
 */
export function checkShifts(shifts: readonly ShiftTimes[], dayStartsAt: string): string[] {
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

  const ordered = [...usable].sort((a, b) => a.start - b.start);
  ordered.forEach((current, at) => {
    const following = ordered[(at + 1) % ordered.length];
    if (!following) return;
    const length = forward(current.start, current.end);
    // Between the two starts. A lone shift is followed by itself, a whole day later.
    const between = ordered.length === 1 ? DAY_MINUTES : forward(current.start, following.start);
    if (length < between) {
      problems.push(`There's a gap between ${clock(current.end)} and ${clock(following.start)}.`);
    } else if (length > between) {
      problems.push(
        `The ${current.code} and ${following.code} shifts overlap from ${clock(following.start)} to ${clock(current.end)}.`,
      );
    }
  });

  const day = minutesOf(dayStartsAt);
  const starts = timed.map((shift) => shift.start);
  if (day !== null && starts.length > 0 && !starts.includes(day)) {
    problems.push("The nursing day must start when one of the shifts starts.");
  }
  return problems;
}
