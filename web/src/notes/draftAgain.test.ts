import { describe, expect, it } from "vitest";
import { ApiError, type Problem } from "../api/errors";
import { DAILY_DRAFT_LIMIT, DRAFT_AGAIN_FAILED, draftAgainOutcome } from "./draftAgain";

const refused = (status: number, code: string) =>
  new ApiError(status, { status, code, title: code } as Problem);

describe("draftAgainOutcome", () => {
  it("treats a draft that someone else already settled as a stale list, not an error", () => {
    expect(draftAgainOutcome(refused(409, "already_drafted"))).toEqual({ kind: "stale" });
    expect(draftAgainOutcome(refused(409, "not_retryable"))).toEqual({ kind: "stale" });
  });

  it("says the daily limit is reached, without a time it resets", () => {
    expect(draftAgainOutcome(refused(429, "daily_draft_limit"))).toEqual({
      kind: "words",
      words: DAILY_DRAFT_LIMIT,
    });
    expect(DAILY_DRAFT_LIMIT).toBe("You've reached today's draft limit. Try again tomorrow.");
  });

  it("says the request did not get through for anything else", () => {
    expect(draftAgainOutcome(new TypeError("network"))).toEqual({
      kind: "words",
      words: DRAFT_AGAIN_FAILED,
    });
    expect(draftAgainOutcome(refused(500, "x"))).toEqual({
      kind: "words",
      words: DRAFT_AGAIN_FAILED,
    });
  });
});
