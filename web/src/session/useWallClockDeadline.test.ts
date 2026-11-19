import { describe, expect, it } from "vitest";
import { WALL_CLOCK_TICK_MS, waitUntil } from "./useWallClockDeadline";

describe("waitUntil", () => {
  it("is null once the deadline has come", () => {
    expect(waitUntil(1_000, 1_000)).toBeNull();
    expect(waitUntil(1_000, 5_000)).toBeNull();
  });
  it("waits for what is left when that is short", () => {
    expect(waitUntil(1_000, 400)).toBe(600);
  });
  it("never waits longer than a tick, so a paused timer clock costs at most a tick", () => {
    expect(waitUntil(10 * 60_000, 0)).toBe(WALL_CLOCK_TICK_MS);
    expect(WALL_CLOCK_TICK_MS).toBeLessThanOrEqual(15_000);
  });
});
