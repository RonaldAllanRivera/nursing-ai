import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "../test/setup";
import { fetchHealth } from "./health";

const HEALTH = "*/api/v1/health";

describe("fetchHealth", () => {
  it("is healthy on a 200 that says healthy", async () => {
    server.use(http.get(HEALTH, () => HttpResponse.json({ status: "healthy", database: "ok" })));
    expect(await fetchHealth()).toEqual({ kind: "healthy" });
  });

  it("is unhealthy when the body says the database is unreachable", async () => {
    server.use(
      http.get(HEALTH, () =>
        HttpResponse.json({ status: "unhealthy", database: "unreachable" }, { status: 503 }),
      ),
    );
    expect(await fetchHealth()).toEqual({ kind: "unhealthy" });
  });

  it("is unreachable on a 503 without that body", async () => {
    server.use(http.get(HEALTH, () => new HttpResponse("busy", { status: 503 })));
    expect(await fetchHealth()).toEqual({ kind: "unreachable" });
  });

  it("is unreachable on a 502 from the dev proxy", async () => {
    server.use(http.get(HEALTH, () => new HttpResponse(null, { status: 502 })));
    expect(await fetchHealth()).toEqual({ kind: "unreachable" });
  });
});
