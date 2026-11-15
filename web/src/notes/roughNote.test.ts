import { describe, expect, it } from "vitest";
import { ApiError } from "../api/errors";
import {
  announceStep,
  countCharacters,
  draftJobQuery,
  isRefused,
  isTransient,
  shouldRetry,
  textState,
} from "./roughNote";

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

describe("isRefused", () => {
  it("is a 4xx answer, not a 5xx or a network error", () => {
    expect(isRefused(new ApiError(422))).toBe(true);
    expect(isRefused(new ApiError(404))).toBe(true);
    expect(isRefused(new ApiError(500))).toBe(false);
    expect(isRefused(new TypeError("Failed to fetch"))).toBe(false);
    expect(isRefused(null)).toBe(false);
  });
});

describe("announceStep", () => {
  it("changes only at 200, 100, 50 and 0 left, and when over", () => {
    expect(announceStep(201)).toBeNull();
    expect(announceStep(200)).toBe(200);
    expect(announceStep(150)).toBe(200);
    expect(announceStep(100)).toBe(100);
    expect(announceStep(51)).toBe(100);
    expect(announceStep(50)).toBe(50);
    expect(announceStep(1)).toBe(50);
    expect(announceStep(0)).toBe(0);
    expect(announceStep(-1)).toBe(-1);
    expect(announceStep(-30)).toBe(-1);
  });
});

describe("draft job polling", () => {
  type Look = { state: { data?: unknown; error?: unknown; dataUpdateCount: number } };
  const interval = (look: Look) =>
    (draftJobQuery("j").refetchInterval as unknown as (q: Look) => number | false)(look);

  it("backs off while the job runs and stops when it is done", () => {
    expect(interval({ state: { data: { status: "queued" }, dataUpdateCount: 1 } })).toBe(1000);
    expect(interval({ state: { data: { status: "running" }, dataUpdateCount: 3 } })).toBe(2000);
    expect(interval({ state: { data: { status: "succeeded" }, dataUpdateCount: 3 } })).toBe(false);
    expect(interval({ state: { data: { status: "failed" }, dataUpdateCount: 3 } })).toBe(false);
  });

  it("stops on a 4xx, but keeps trying through a network or 5xx error", () => {
    const state = { data: { status: "queued" }, dataUpdateCount: 1 };
    expect(interval({ state: { ...state, error: new ApiError(404) } })).toBe(false);
    expect(interval({ state: { ...state, error: new ApiError(503) } })).toBe(1000);
    expect(interval({ state: { ...state, error: new TypeError("Failed to fetch") } })).toBe(1000);
  });
});
