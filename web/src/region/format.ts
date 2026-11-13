import type { components } from "../api/schema";
import type { Locale } from "./words";

type ShiftRef = components["schemas"]["ShiftRef"];
type Clock = "24h" | "12h";

// Every function takes the zone explicitly: the browser's own zone is never used.

function parts(iso: string, locale: Locale, options: Intl.DateTimeFormatOptions) {
  const found: Record<string, string> = {};
  for (const part of new Intl.DateTimeFormat(locale, options).formatToParts(new Date(iso))) {
    found[part.type] = part.value;
  }
  return found;
}

function dayMonth(iso: string, timeZone: string, locale: Locale) {
  const p = parts(iso, locale, { timeZone, day: "numeric", month: "short", year: "numeric" });
  return { day: p["day"] ?? "", month: p["month"] ?? "", year: p["year"] ?? "" };
}

/** `"12 Nov 2026"`: day first and a month name, so no one reads 11/12 the wrong way round. */
export function formatDate(iso: string, opts: { timeZone: string; locale: Locale }): string {
  const { day, month, year } = dayMonth(iso, opts.timeZone, opts.locale);
  return `${day} ${month} ${year}`;
}

/** `"05:10"` on the 24-hour clock; `"5:10 AM"` (or `"10 PM"` on the hour) on the 12-hour one. */
export function formatTime(
  iso: string,
  opts: { timeZone: string; locale: Locale; clock: Clock },
): string {
  const { timeZone, locale, clock } = opts;
  if (clock === "24h") {
    const p = parts(iso, locale, {
      timeZone,
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    });
    return `${p["hour"] ?? ""}:${p["minute"] ?? ""}`;
  }
  const p = parts(iso, locale, { timeZone, hour: "numeric", minute: "2-digit", hourCycle: "h12" });
  const period = (p["dayPeriod"] ?? "").toUpperCase();
  const hour = p["hour"] ?? "";
  return p["minute"] === "00" ? `${hour} ${period}` : `${hour}:${p["minute"] ?? ""} ${period}`;
}

/**
 * A shift in its own zone: `"22:00 11 Nov to 06:00 12 Nov 2026"`. One date when both ends fall
 * on the same day, and the year on both dates when it differs.
 */
export function formatShiftRange(shift: ShiftRef, opts: { locale: Locale; clock: Clock }): string {
  const { locale, clock } = opts;
  const timeZone = shift.timezone;
  const start = dayMonth(shift.starts_at, timeZone, locale);
  const end = dayMonth(shift.ends_at, timeZone, locale);
  const from = formatTime(shift.starts_at, { timeZone, locale, clock });
  const to = formatTime(shift.ends_at, { timeZone, locale, clock });
  const sameDay = start.day === end.day && start.month === end.month && start.year === end.year;
  if (sameDay) return `${from} to ${to} ${end.day} ${end.month} ${end.year}`;
  if (start.year === end.year) {
    return `${from} ${start.day} ${start.month} to ${to} ${end.day} ${end.month} ${end.year}`;
  }
  return `${from} ${start.day} ${start.month} ${start.year} to ${to} ${end.day} ${end.month} ${end.year}`;
}
