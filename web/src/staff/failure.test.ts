import { describe, expect, it } from "vitest";
import { ApiError } from "../api/errors";
import { PIN_CONNECTION } from "../session/pin";
import { NOT_CHANGED, failureKind, staffFailureWords } from "./failure";

const refused = (status: number, code: string) =>
  new ApiError(status, { type: "about:blank", title: "No", status, code } as never);

describe("what a failed staff action means", () => {
  it("is a wrong PIN, which stays in the dialog", () => {
    expect(failureKind(refused(403, "pin_wrong"))).toBe("wrong_pin");
  });

  it("is a locked PIN, which the lock screen takes over", () => {
    expect(failureKind(refused(423, "pin_locked"))).toBe("gate");
  });

  it("is a stale list when the person is gone or the action is no longer allowed", () => {
    expect(failureKind(refused(404, "not_found"))).toBe("stale");
    expect(failureKind(refused(403, "forbidden"))).toBe("stale");
  });

  it("stays in the dialog, saying nothing changed, when the token was stale (not a stale list)", () => {
    const stale = refused(403, "csrf_failed");
    expect(failureKind(stale)).toBe("stay");
    expect(staffFailureWords(stale)).toBe(NOT_CHANGED);
    expect(NOT_CHANGED).toBe("That change was not saved. Enter your PIN and try again.");
    expect(staffFailureWords(new TypeError("Failed to fetch"))).toBe(PIN_CONNECTION);
  });

  it("stays in the dialog for a connection failure or a server error, so the person can try again", () => {
    expect(failureKind(new TypeError("Failed to fetch"))).toBe("stay");
    expect(failureKind(refused(500, "internal"))).toBe("stay");
    expect(failureKind(refused(503, "unavailable"))).toBe("stay");
  });
});
