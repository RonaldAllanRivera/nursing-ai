import { describe, expect, it } from "vitest";
import { isPastExpiry, sessionEndedWords } from "./expiry";

describe("sessionEndedWords", () => {
  it("names the facility's hours", () => {
    expect(sessionEndedWords(12)).toBe("Your session ended after 12 hours. Sign in again.");
    expect(sessionEndedWords(14)).toBe("Your session ended after 14 hours. Sign in again.");
  });
  it("says 1 hour in the singular", () => {
    expect(sessionEndedWords(1)).toBe("Your session ended after 1 hour. Sign in again.");
  });
});

describe("isPastExpiry", () => {
  const at = "2026-11-17T10:00:00.000Z";
  const t = Date.parse(at);
  it("is false before and true from the instant", () => {
    expect(isPastExpiry(at, t - 1)).toBe(false);
    expect(isPastExpiry(at, t)).toBe(true);
  });
  it("is false for a value that is no date", () => {
    expect(isPastExpiry("", t)).toBe(false);
  });
});
