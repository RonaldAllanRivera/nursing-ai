import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import { server } from "../test/setup";
import { api, REQUEST_TIMEOUT_MS } from "./client";

// Captured before a test fakes the timers: the real I/O between the faked steps needs real time.
const realSetTimeout = globalThis.setTimeout;

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

  it("waits 35 s: longer than the live API's worst case (the HTTP API cuts at 30 s)", async () => {
    expect(REQUEST_TIMEOUT_MS).toBe(35_000);
    vi.useFakeTimers({ toFake: ["setTimeout"] });
    let answer: () => void = () => undefined;
    server.use(
      http.get(
        "*/api/v1/health",
        () =>
          new Promise<Response>((resolve) => {
            answer = () => {
              resolve(HttpResponse.json({ status: "healthy", database: "ok" }));
            };
          }),
      ),
    );
    const pending = api.GET("/api/v1/health");
    await vi.advanceTimersByTimeAsync(29_000);
    answer();
    const { response } = await pending;
    expect(response.status).toBe(200);
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

  describe("a 401 whose re-read is also a 401 (two tabs)", () => {
    const unauthorised = () =>
      HttpResponse.json(
        { type: "about:blank", title: "Sign in", status: 401, code: "not_signed_in" },
        { status: 401 },
      );
    const me = { user_id: "u1", gate: "open", csrf_token: "t", kind: "persona" };
    /** Steps the faked clock 50 ms at a time, letting the real I/O between the steps finish. */
    const tick = async () => {
      await vi.advanceTimersByTimeAsync(50);
      await new Promise<void>((resolve) => {
        realSetTimeout(resolve, 5);
      });
    };

    it("waits 1 s and re-reads once more before it lets the 401 stand", async () => {
      vi.useFakeTimers({ toFake: ["setTimeout"] });
      let reads = 0;
      let health = 0;
      server.use(
        http.get("*/api/v1/health", () => {
          health += 1;
          return health === 1
            ? unauthorised()
            : HttpResponse.json({ status: "healthy", database: "ok" });
        }),
        http.get("*/api/v1/session", () => {
          reads += 1;
          // The first re-read left with the cookie the other tab's unlock had just rotated.
          return reads === 1 ? unauthorised() : HttpResponse.json(me);
        }),
      );
      const pending = api.GET("/api/v1/health");
      while (reads < 1) await tick();
      let waited = 0;
      while (reads < 2 && waited < 5_000) {
        await tick();
        waited += 50;
      }
      expect(reads).toBe(2);
      expect(waited).toBeGreaterThanOrEqual(950);
      const { response } = await pending;
      expect(health).toBe(2);
      expect(response.status).toBe(200);
    });

    it("lets the 401 stand when the second re-read is a 401 too", async () => {
      vi.useFakeTimers({ toFake: ["setTimeout"] });
      let reads = 0;
      server.use(
        http.get("*/api/v1/health", unauthorised),
        http.get("*/api/v1/session", () => {
          reads += 1;
          return unauthorised();
        }),
      );
      const pending = api.GET("/api/v1/health");
      while (reads < 1) await tick();
      for (let step = 0; step < 40; step += 1) await tick();
      const { response } = await pending;
      expect(response.status).toBe(401);
      expect(reads).toBe(2);
    });
  });
});
