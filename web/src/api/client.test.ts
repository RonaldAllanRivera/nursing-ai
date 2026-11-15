import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import { server } from "../test/setup";
import { api, REQUEST_TIMEOUT_MS } from "./client";

describe("api client", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("reads location when a request is made, not when the module loads", async () => {
    let seen = "";
    server.use(
      http.get("*/api/v1/health", ({ request }) => {
        seen = new URL(request.url).origin;
        return HttpResponse.json({ status: "healthy", database: "ok" });
      }),
    );
    vi.stubGlobal("location", new URL("http://lan-host.test:4321/"));
    await api.GET("/api/v1/health");
    expect(seen).toBe("http://lan-host.test:4321");
  });

  it("aborts a request that takes longer than the timeout", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout"] });
    server.use(http.get("*/api/v1/health", () => new Promise(() => undefined)));
    const pending = api.GET("/api/v1/health").catch((error: unknown) => error);
    await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS + 1);
    const error = await pending;
    expect(error).toBeInstanceOf(DOMException);
    expect((error as DOMException).name).toBe("TimeoutError");
  });

  it("still times out when the caller passes a signal", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout"] });
    server.use(http.get("*/api/v1/health", () => new Promise(() => undefined)));
    const caller = new AbortController();
    const pending = api
      .GET("/api/v1/health", { signal: caller.signal })
      .catch((error: unknown) => error);
    await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS + 1);
    const error = await pending;
    expect(error).toBeInstanceOf(DOMException);
    expect((error as DOMException).name).toBe("TimeoutError");
  });

  it("cancels the request when the caller aborts", async () => {
    server.use(http.get("*/api/v1/health", () => new Promise(() => undefined)));
    const caller = new AbortController();
    const pending = api
      .GET("/api/v1/health", { signal: caller.signal })
      .catch((error: unknown) => error);
    caller.abort(new DOMException("gone", "AbortError"));
    const error = await pending;
    expect((error as DOMException).name).toBe("AbortError");
  });

  it("cancels at once when the caller's signal is already aborted", async () => {
    server.use(http.get("*/api/v1/health", () => new Promise(() => undefined)));
    const error = await api
      .GET("/api/v1/health", { signal: AbortSignal.abort(new DOMException("gone", "AbortError")) })
      .catch((e: unknown) => e);
    expect((error as DOMException).name).toBe("AbortError");
  });
});
