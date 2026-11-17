import { http, HttpResponse } from "msw";
import { QueryClient } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { sessionKey, type Session } from "../session/session";
import { server } from "../test/setup";
import { api, readSessionFrom } from "./client";
import { csrfHeaders } from "./csrf";

const session = { csrf_token: "token-one" } as Session;

describe("csrfHeaders", () => {
  it.each(["POST", "put", "Patch", "DELETE"])("sends the token on %s", (method) => {
    expect(csrfHeaders(method, session)).toEqual({ "X-CSRF-Token": "token-one" });
  });

  it.each(["GET", "head", "OPTIONS"])("sends nothing on %s", (method) => {
    expect(csrfHeaders(method, session)).toEqual({});
  });

  it("sends nothing without a session", () => {
    expect(csrfHeaders("POST", null)).toEqual({});
    expect(csrfHeaders("POST", undefined)).toEqual({});
  });
});

describe("the api client", () => {
  let queryClient: QueryClient;
  beforeEach(() => {
    queryClient = new QueryClient();
    readSessionFrom(() => queryClient.getQueryData<Session | null>(sessionKey));
  });
  afterEach(() => {
    readSessionFrom(() => undefined);
  });

  function record() {
    const seen: Record<string, string | null> = {};
    const answer = (request: Request) => {
      seen[request.method] = request.headers.get("X-CSRF-Token");
      return HttpResponse.json({});
    };
    server.use(
      http.get("*/api/v1/health", ({ request }) => answer(request)),
      http.post("*/api/v1/health", ({ request }) => answer(request)),
      http.put("*/api/v1/health", ({ request }) => answer(request)),
      http.patch("*/api/v1/health", ({ request }) => answer(request)),
      http.delete("*/api/v1/health", ({ request }) => answer(request)),
    );
    return seen;
  }

  async function sendAll() {
    const url = "/api/v1/health" as never;
    await Promise.all([
      api.GET(url),
      api.POST(url, {} as never),
      api.PUT(url, {} as never),
      api.PATCH(url, {} as never),
      api.DELETE(url, {} as never),
    ]);
  }

  it("adds the CSRF header to unsafe requests only", async () => {
    queryClient.setQueryData(sessionKey, session);
    const seen = record();
    await sendAll();
    expect(seen).toEqual({
      GET: null,
      POST: "token-one",
      PUT: "token-one",
      PATCH: "token-one",
      DELETE: "token-one",
    });
  });

  it("sends no header without a session", async () => {
    queryClient.setQueryData(sessionKey, null);
    const seen = record();
    await sendAll();
    expect(Object.values(seen).every((value) => value === null)).toBe(true);
  });

  it("keeps the headers the call already passes", async () => {
    queryClient.setQueryData(sessionKey, session);
    let headers: Headers | undefined;
    server.use(
      http.put("*/api/v1/health", ({ request }) => {
        headers = request.headers;
        return HttpResponse.json({});
      }),
    );
    await api.PUT(
      "/api/v1/health" as never,
      {
        headers: { "Idempotency-Key": "key-1" },
        params: { header: { "If-Match": "v3" } },
      } as never,
    );
    expect(headers?.get("X-CSRF-Token")).toBe("token-one");
    expect(headers?.get("Idempotency-Key")).toBe("key-1");
    expect(headers?.get("If-Match")).toBe("v3");
  });
});
