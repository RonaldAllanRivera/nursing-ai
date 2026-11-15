import { describe, expect, it } from "vitest";
import { ApiError } from "../api/errors";
import { createQueryClient, retryQuery } from "./queryClient";

describe("retryQuery", () => {
  it.each([400, 401, 403, 404, 422, 499])("does not retry a %s answer", (status) => {
    expect(retryQuery(0, new ApiError(status))).toBe(false);
  });

  it.each([500, 502, 503])("retries a %s answer, three times in all", (status) => {
    const error = new ApiError(status);
    expect([0, 1, 2, 3].map((n) => retryQuery(n, error))).toEqual([true, true, true, false]);
  });

  it("retries a network failure like any other error", () => {
    const error = new TypeError("Failed to fetch");
    expect(retryQuery(0, error)).toBe(true);
    expect(retryQuery(3, error)).toBe(false);
  });

  it("is the app's default for queries", () => {
    expect(createQueryClient().getDefaultOptions().queries?.retry).toBe(retryQuery);
  });
});
