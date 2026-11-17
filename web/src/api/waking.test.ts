import { describe, expect, it } from "vitest";
import { retryQuery } from "./retry";
import { ApiError, type Problem } from "./errors";
import { isWaking, wakeRetryDelay } from "./waking";

const waking = new ApiError(503, {
  status: 503,
  code: "database_waking",
  title: "Waking",
  type: "about:blank",
} satisfies Problem);

describe("waking", () => {
  it("waking retries every 5 s and gives up after 60 s", () => {
    const waits = Array.from({ length: 12 }, (_, n) => wakeRetryDelay(n));
    expect(waits).toEqual(Array<number>(12).fill(5000));
    expect(wakeRetryDelay(12)).toBeNull();
    expect(wakeRetryDelay(40)).toBeNull();
    expect(waits.reduce<number>((sum, wait) => sum + (wait ?? 0), 0)).toBe(60_000);
  });

  it("the query retry predicate follows that schedule", () => {
    expect(retryQuery(0, waking)).toBe(true);
    expect(retryQuery(11, waking)).toBe(true);
    expect(retryQuery(12, waking)).toBe(false);
  });

  it("only a 503 database_waking answer is waking", () => {
    expect(isWaking(waking)).toBe(true);
    expect(isWaking(new ApiError(503))).toBe(false);
    expect(isWaking(new TypeError("x"))).toBe(false);
  });
});
