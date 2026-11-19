import { describe, expect, it } from "vitest";
import { HEARTBEAT_MS, heartbeatDue, idleState } from "./idle";

describe("idleState", () => {
  const start = 1_000_000;
  it("is open just under the limit and says how long is left", () => {
    expect(idleState(start, start + 299_999, 300)).toEqual({ locked: false, msLeft: 1 });
  });
  it("is locked exactly at the limit", () => {
    expect(idleState(start, start + 300_000, 300)).toEqual({ locked: true, msLeft: 0 });
  });
  it("is locked over the limit (a sleeping machine woke late)", () => {
    expect(idleState(start, start + 3_600_000, 300).locked).toBe(true);
  });
  it("counts again from a reset", () => {
    const reset = start + 200_000;
    expect(idleState(reset, start + 400_000, 300)).toEqual({ locked: false, msLeft: 100_000 });
  });
  it("treats a clock that went backwards as just active", () => {
    expect(idleState(start, start - 5_000, 300)).toEqual({ locked: false, msLeft: 300_000 });
  });
});

describe("heartbeatDue", () => {
  it("waits a full minute since the last one", () => {
    expect(heartbeatDue(0, HEARTBEAT_MS - 1)).toBe(false);
    expect(heartbeatDue(0, HEARTBEAT_MS)).toBe(true);
  });
});
