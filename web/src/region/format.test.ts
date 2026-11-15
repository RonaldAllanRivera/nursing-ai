import { afterEach, describe, expect, it, vi } from "vitest";
import type { components } from "../api/schema";
import { formatDate, formatShiftRange, formatTime } from "./format";

type ShiftRef = components["schemas"]["ShiftRef"];

const manila = "Asia/Manila";
const la = "America/Los_Angeles";

function shift(starts_at: string, ends_at: string, timezone: string): ShiftRef {
  return { code: "x", label: "x", shift_date: "2026-11-11", starts_at, ends_at, timezone };
}

describe("formatDate", () => {
  it("puts the day first and spells the month in both locales", () => {
    const iso = "2026-11-12T01:00:00Z";
    expect(formatDate(iso, { timeZone: manila, locale: "en-PH" })).toBe("12 Nov 2026");
    expect(formatDate(iso, { timeZone: la, locale: "en-US" })).toBe("11 Nov 2026");
  });
});

describe("formatTime", () => {
  it("shows 24-hour time with leading zeros", () => {
    expect(
      formatTime("2026-11-11T21:10:00Z", { timeZone: manila, locale: "en-PH", clock: "24h" }),
    ).toBe("05:10");
  });

  it("shows 12-hour time, dropping the minutes on the hour", () => {
    const base = { timeZone: la, locale: "en-US", clock: "12h" } as const;
    expect(formatTime("2026-11-12T13:10:00Z", base)).toBe("5:10 AM");
    expect(formatTime("2026-11-12T06:00:00Z", base)).toBe("10 PM");
  });
});

describe("formatShiftRange", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("formats a PH night shift range in Manila time from a US browser", () => {
    vi.stubEnv("TZ", la);
    const night = shift("2026-11-11T14:00:00Z", "2026-11-11T22:00:00Z", manila);
    expect(formatShiftRange(night, { locale: "en-PH", clock: "24h" })).toBe(
      "22:00 11 Nov to 06:00 12 Nov 2026",
    );
  });

  it("shows one date when both ends fall on the same day", () => {
    const day = shift("2026-11-11T22:00:00Z", "2026-11-12T06:00:00Z", manila);
    expect(formatShiftRange(day, { locale: "en-PH", clock: "24h" })).toBe(
      "06:00 to 14:00 12 Nov 2026",
    );
  });

  it("carries the year on both dates across New Year", () => {
    const nye = shift("2026-12-31T14:00:00Z", "2026-12-31T22:00:00Z", manila);
    expect(formatShiftRange(nye, { locale: "en-PH", clock: "24h" })).toBe(
      "22:00 31 Dec 2026 to 06:00 1 Jan 2027",
    );
  });

  it("uses the 12-hour clock when the profile says so", () => {
    const night = shift("2026-11-12T06:00:00Z", "2026-11-12T14:00:00Z", la);
    expect(formatShiftRange(night, { locale: "en-US", clock: "12h" })).toBe(
      "10 PM 11 Nov to 6 AM 12 Nov 2026",
    );
  });
});
