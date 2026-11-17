import { describe, expect, it } from "vitest";
import {
  DEMO_BANNER,
  GOOGLE_START,
  SIGN_IN_FALLBACK,
  SIGN_IN_MESSAGES,
  offeredFrom,
  signInErrorFrom,
} from "./signInOptions";

describe("signInErrorFrom", () => {
  it("accepts exactly the three values the server redirects with", () => {
    expect(signInErrorFrom({ error: "no_access" })).toBe("no_access");
    expect(signInErrorFrom({ error: "expired" })).toBe("expired");
    expect(signInErrorFrom({ error: "cancelled" })).toBe("cancelled");
  });

  it("treats anything else as absent", () => {
    expect(signInErrorFrom({ error: "boom" })).toBeUndefined();
    expect(signInErrorFrom({ error: 7 })).toBeUndefined();
    expect(signInErrorFrom({ error: ["no_access"] })).toBeUndefined();
    expect(signInErrorFrom({})).toBeUndefined();
  });
});

describe("the words", () => {
  it("uses the agreed sentence for no_access and tells what to do in the others", () => {
    expect(SIGN_IN_MESSAGES.no_access).toBe(
      "You don't have access yet. Ask the admin to invite your Google account.",
    );
    expect(SIGN_IN_MESSAGES.expired).toMatch(/Sign in with Google again\.$/);
    expect(SIGN_IN_MESSAGES.cancelled).toMatch(/Sign in again/);
    expect(DEMO_BANNER).toBe("Synthetic patients only. Never type real patient details.");
    expect(GOOGLE_START).toBe("/api/v1/auth/google/start");
  });
});

describe("offeredFrom", () => {
  it("offers Google first and the personas with their PIN when both are on", () => {
    expect(offeredFrom({ google: true, personas: true, demo: true, demo_pin: "135790" })).toEqual({
      google: true,
      personas: true,
      demoPin: "135790",
      banner: true,
    });
  });

  it("offers only what is on, and no PIN line without a PIN", () => {
    expect(offeredFrom({ google: true, personas: false, demo: false, demo_pin: null })).toEqual({
      google: true,
      personas: false,
      demoPin: null,
      banner: false,
    });
  });

  it("falls back to the personas alone, with no Google link, PIN line or banner", () => {
    expect(offeredFrom(undefined)).toEqual(SIGN_IN_FALLBACK);
    expect(SIGN_IN_FALLBACK).toEqual({
      google: false,
      personas: true,
      demoPin: null,
      banner: false,
    });
  });
});
