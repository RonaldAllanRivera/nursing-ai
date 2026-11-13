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
});
