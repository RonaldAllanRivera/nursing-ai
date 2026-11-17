import { describe, expect, it } from "vitest";
import { ApiError } from "./errors";
import { retryOptions, retryQuery } from "./retry";

describe("retryOptions", () => {
  it("stops at once on a 501 and otherwise follows retryQuery", () => {
    expect(retryOptions(0, new ApiError(501))).toBe(false);
    expect(retryOptions(0, new ApiError(500))).toBe(retryQuery(0, new ApiError(500)));
    expect(retryOptions(3, new ApiError(500))).toBe(false);
    expect(retryOptions(0, new ApiError(404))).toBe(false);
    expect(retryOptions(1, new Error("offline"))).toBe(true);
  });
});
