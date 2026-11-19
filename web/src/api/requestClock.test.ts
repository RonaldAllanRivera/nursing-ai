import { delay, http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import { server } from "../test/setup";
import { api } from "./client";
import {
  lastRefreshingRequest,
  noteRequest,
  refreshesServerIdle,
  resetRequestClock,
} from "./requestClock";

afterEach(() => {
  resetRequestClock();
});

describe("refreshesServerIdle", () => {
  it("is true for every request but the draft-job poll", () => {
    expect(refreshesServerIdle("GET", "/api/v1/session")).toBe(true);
    expect(refreshesServerIdle("GET", "/api/v1/patients")).toBe(true);
    expect(refreshesServerIdle("POST", "/api/v1/notes")).toBe(true);
    expect(refreshesServerIdle("PUT", "/api/v1/session/shift")).toBe(true);
    expect(refreshesServerIdle("GET", "/api/v1/draft-jobs/{job_id}")).toBe(false);
    expect(refreshesServerIdle("GET", "/api/v1/draft-jobs/abc-123")).toBe(false);
  });
  it("keeps counting anything else under the draft-jobs address", () => {
    expect(refreshesServerIdle("POST", "/api/v1/draft-jobs/{job_id}")).toBe(true);
    expect(refreshesServerIdle("GET", "/api/v1/draft-jobs/abc/extra")).toBe(true);
  });
});

describe("a slow request", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("counts from when its answer arrives too: the server stamps it before it answers", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"], shouldAdvanceTime: true });
    server.use(
      http.get("*/api/v1/patients", async () => {
        await delay(8_000);
        return HttpResponse.json([]);
      }),
      http.get("*/api/v1/draft-jobs/:id", async () => {
        await delay(8_000);
        return HttpResponse.json({}, { status: 404 });
      }),
    );
    const sentAt = Date.now();
    const call = api.GET("/api/v1/patients");
    expect(lastRefreshingRequest()).toBe(sentAt);
    await vi.advanceTimersByTimeAsync(8_000);
    await call;
    expect(lastRefreshingRequest()).toBeGreaterThanOrEqual(sentAt + 8_000);

    // The poll never counts, sent or answered.
    resetRequestClock();
    const poll = api.GET("/api/v1/draft-jobs/{job_id}", { params: { path: { job_id: "x" } } });
    await vi.advanceTimersByTimeAsync(8_000);
    await poll;
    expect(lastRefreshingRequest()).toBeNull();
  });
});

describe("the request clock", () => {
  it("remembers when the last counting request was sent, and forgets on reset", () => {
    expect(lastRefreshingRequest()).toBeNull();
    noteRequest("GET", "/api/v1/patients", 5_000);
    noteRequest("GET", "/api/v1/draft-jobs/{job_id}", 9_000);
    expect(lastRefreshingRequest()).toBe(5_000);
    resetRequestClock();
    expect(lastRefreshingRequest()).toBeNull();
  });

  it("is fed by every request the api client sends, but not by the poll", async () => {
    server.use(
      http.get("*/api/v1/patients", () => HttpResponse.json([])),
      http.get("*/api/v1/draft-jobs/:id", () => HttpResponse.json({}, { status: 404 })),
    );
    await api.GET("/api/v1/draft-jobs/{job_id}", { params: { path: { job_id: "x" } } });
    expect(lastRefreshingRequest()).toBeNull();
    const before = Date.now();
    await api.GET("/api/v1/patients");
    expect(lastRefreshingRequest()).toBeGreaterThanOrEqual(before);
  });
});
