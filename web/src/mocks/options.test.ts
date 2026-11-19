import { describe, expect, it } from "vitest";
import { MOCK_OPTIONS_GLOBAL, readMockOptions } from "./options";

describe("readMockOptions", () => {
  it("names the global Playwright sets", () => {
    expect(MOCK_OPTIONS_GLOBAL).toBe("__SOURCELINE_MOCK__");
  });

  it("keeps every well-formed field", () => {
    const given = {
      google: true,
      demo: false,
      personaGate: "enter_pin",
      account: { user: "someone@example.com", gate: "set_pin" },
      failDraft: "provider_error",
    };
    expect(readMockOptions(given)).toEqual(given);
  });

  it("drops bad fields and anything unknown", () => {
    expect(
      readMockOptions({
        google: "yes",
        demo: 1,
        personaGate: "idle_locked",
        account: { user: 7, gate: "open" },
        failDraft: "exploded",
        extra: true,
      }),
    ).toEqual({});
  });

  it("drops a bad account gate but keeps the user, and defaults to nothing", () => {
    expect(readMockOptions({ account: { user: "a@example.com", gate: "nope" } })).toEqual({
      account: { user: "a@example.com" },
    });
    expect(readMockOptions(undefined)).toEqual({});
    expect(readMockOptions("text")).toEqual({});
    expect(readMockOptions(null)).toEqual({});
    expect(readMockOptions([])).toEqual({});
  });
});
