import { describe, expect, it } from "vitest";
import { ApiError } from "../api/errors";
import { countCharacters, isTransient, shouldRetry, textState } from "./roughNote";

describe("isTransient", () => {
  it("is true for a network error, a timeout and a 5xx", () => {
    expect(isTransient(new TypeError("Failed to fetch"))).toBe(true);
    expect(isTransient(new DOMException("too long", "TimeoutError"))).toBe(true);
    expect(isTransient(new ApiError(500))).toBe(true);
    expect(isTransient(new ApiError(503))).toBe(true);
  });

  it("is false for a 4xx and for anything else", () => {
    expect(isTransient(new ApiError(401))).toBe(false);
    expect(isTransient(new ApiError(422))).toBe(false);
    expect(isTransient(new Error("boom"))).toBe(false);
  });
});

describe("shouldRetry", () => {
  it("retries a transient error twice, never a 4xx", () => {
    expect(shouldRetry(0, new ApiError(500))).toBe(true);
    expect(shouldRetry(1, new ApiError(500))).toBe(true);
    expect(shouldRetry(2, new ApiError(500))).toBe(false);
    expect(shouldRetry(0, new ApiError(422))).toBe(false);
  });
});

describe("textState", () => {
  it("counts code points, like the server", () => {
    expect(countCharacters("ab😀")).toBe(3);
  });

  it("treats spaces only as empty", () => {
    expect(textState("   \n ")).toMatchObject({ canSave: false, showCount: false });
    expect(textState("")).toMatchObject({ canSave: false });
  });

  it("shows how many are left only in the last 200", () => {
    expect(textState("a".repeat(3799))).toMatchObject({ showCount: false, canSave: true });
    expect(textState("a".repeat(3800))).toMatchObject({ showCount: true, left: 200 });
    expect(textState("a".repeat(4000))).toMatchObject({ showCount: true, left: 0, canSave: true });
    expect(textState("a".repeat(4001))).toMatchObject({ left: -1, canSave: false });
  });
});
