import { describe, expect, it } from "vitest";
import { idleState, SERVER_SLACK_MS } from "./idle";

describe("idleState with the server's own idle clock", () => {
  const start = 1_000_000;
  it("waits until the server would have locked, plus its slack, after a request", () => {
    // A request at 250 s restarts the server's count: the browser locks at 250 + 300 + 5 s.
    const request = start + 250_000;
    expect(idleState(start, start + 300_000, 300, request)).toEqual({
      locked: false,
      msLeft: 255_000,
    });
    expect(idleState(start, start + 555_000 - 1, 300, request).locked).toBe(false);
    expect(idleState(start, start + 250_000 + 300_000 + SERVER_SLACK_MS, 300, request).locked).toBe(
      true,
    );
  });
  it("uses the later of the two clocks, so a request never locks it sooner", () => {
    const request = start + 10_000;
    const activity = start + 200_000;
    expect(idleState(activity, start + 499_999, 300, request).locked).toBe(false);
    expect(idleState(activity, start + 500_000, 300, request).locked).toBe(true);
  });
  it("ignores a request time from the future (the clock stepped back)", () => {
    expect(idleState(start, start + 300_000, 300, start + 9_000_000).locked).toBe(true);
  });
  it("is the old rule when no request has been sent", () => {
    expect(idleState(start, start + 300_000, 300, null).locked).toBe(true);
    expect(idleState(start, start + 299_999, 300).locked).toBe(false);
  });
});
