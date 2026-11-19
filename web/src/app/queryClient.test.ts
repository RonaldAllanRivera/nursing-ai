import { onlineManager, QueryObserver } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it } from "vitest";
import { ApiError, type Problem } from "../api/errors";
import { patchGate } from "../session/gate";
import { sessionKey, sessionQuery, type Session } from "../session/session";
import { server } from "../test/setup";
import { retryQuery } from "../api/retry";
import { createQueryClient } from "./queryClient";

const problem = (status: number, code: Problem["code"]): Problem => ({
  status,
  code,
  title: "x",
  type: "about:blank",
});
const session = { gate: "open", csrf_token: "t", kind: "persona" } as Session;

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

describe("the server's answers move the app, not its data", () => {
  it("a 423 sets the cached session's gate and drops the patient data behind it", async () => {
    const client = createQueryClient();
    client.setQueryData(sessionKey, session);
    client.setQueryData(["patients"], [{ id: "p1" }]);
    await client
      .query({
        queryKey: ["patient", "p1"],
        queryFn: () => Promise.reject(new ApiError(423, problem(423, "enter_pin"))),
        retry: false,
      })
      .catch(() => undefined);
    expect(client.getQueryData(sessionKey)).toEqual({ ...session, gate: "enter_pin" });
    expect(client.getQueryData(["patients"])).toBeUndefined();
  });

  it("a 423 on a write sets the gate too, and never signs her out", async () => {
    const client = createQueryClient();
    client.setQueryData(sessionKey, session);
    await client
      .getMutationCache()
      .build(client, {
        mutationFn: () => Promise.reject(new ApiError(423, problem(423, "idle_locked"))),
      })
      .execute(undefined)
      .catch(() => undefined);
    expect(client.getQueryData<Session>(sessionKey)?.gate).toBe("idle_locked");
  });

  it("a 423 with no cached session does not invent one", async () => {
    const client = createQueryClient();
    await client
      .query({
        queryKey: ["x"],
        queryFn: () => Promise.reject(new ApiError(423, problem(423, "set_pin"))),
        retry: false,
      })
      .catch(() => undefined);
    expect(client.getQueryData(sessionKey)).toBeUndefined();
  });

  it("a 403 csrf_failed makes the session query fetch again", async () => {
    let calls = 0;
    server.use(
      http.get("*/api/v1/session", () => {
        calls += 1;
        return HttpResponse.json(session);
      }),
    );
    const client = createQueryClient();
    const observer = new QueryObserver(client, sessionQuery);
    const unsubscribe = observer.subscribe(() => undefined);
    await expect.poll(() => calls).toBe(1);
    await client
      .query({
        queryKey: ["x"],
        queryFn: () => Promise.reject(new ApiError(403, problem(403, "csrf_failed"))),
        retry: false,
      })
      .catch(() => undefined);
    await expect.poll(() => calls).toBe(2);
    unsubscribe();
  });
});

describe("behind a lock screen", () => {
  const held = ["held-note", "p1"];

  it("drops patient and note data and finished writes, and keeps what a lock screen needs", async () => {
    const client = createQueryClient();
    client.setQueryData(sessionKey, session);
    client.setQueryData(["patients"], [{ id: "p1" }]);
    client.setQueryData(["patient", "p1"], { name: "x" });
    client.setQueryData(["note", "n1"], { text: "draft" });
    client.setQueryData(["draft-job", "j1"], { status: "running" });
    client.setQueryData(["facility", "ph-demo"], { profile: {} });
    client.setQueryData(held, { text: "BP 90/60", owner: null });
    client.setQueryData(["personas"], [1]);
    client.setQueryData(["sign-in-options"], { demo: true });
    await client
      .getMutationCache()
      .build(client, { mutationFn: () => Promise.resolve("saved") })
      .execute({ edited: "line text" });
    expect(client.getMutationCache().getAll()).toHaveLength(1);
    patchGate(client, "idle_locked");
    expect(client.getQueryData(["patients"])).toBeUndefined();
    expect(client.getQueryData(["patient", "p1"])).toBeUndefined();
    expect(client.getQueryData(["note", "n1"])).toBeUndefined();
    expect(client.getQueryData(["draft-job", "j1"])).toBeUndefined();
    expect(client.getMutationCache().getAll()).toHaveLength(0);
    expect(client.getQueryData(held)).toEqual({ text: "BP 90/60", owner: null });
    expect(client.getQueryData(["facility", "ph-demo"])).toEqual({ profile: {} });
    expect(client.getQueryData(["personas"])).toEqual([1]);
    expect(client.getQueryData(["sign-in-options"])).toEqual({ demo: true });
    expect(client.getQueryData<Session>(sessionKey)?.gate).toBe("idle_locked");
  });

  it("drops nothing when the gate opens again, or moves between locked gates", () => {
    const client = createQueryClient();
    client.setQueryData(sessionKey, { ...session, gate: "idle_locked" });
    client.setQueryData(["patients"], [{ id: "p1" }]);
    patchGate(client, "enter_pin");
    patchGate(client, "pin_locked");
    client.setQueryData(sessionKey, { ...session, gate: "open" });
    expect(client.getQueryData(["patients"])).toEqual([{ id: "p1" }]);
  });
});

describe("waiting out a waking database", () => {
  const waking = new ApiError(503, problem(503, "database_waking"));

  it("queries wait 5 s for a waking answer and back off for anything else", () => {
    const { retryDelay } = createQueryClient().getDefaultOptions().queries ?? {};
    const wait = retryDelay as (n: number, e: Error) => number;
    expect(wait(0, waking)).toBe(5000);
    expect(wait(7, waking)).toBe(5000);
    expect(wait(0, new Error("x"))).toBe(1000);
    expect(wait(2, new Error("x"))).toBe(4000);
    expect(wait(9, new Error("x"))).toBe(30000);
  });

  it("writes retry only a waking answer, and wait 5 s for it", () => {
    const { retry, retryDelay } = createQueryClient().getDefaultOptions().mutations ?? {};
    const again = retry as (n: number, e: Error) => boolean;
    const wait = retryDelay as (n: number, e: Error) => number;
    expect(again(0, waking)).toBe(true);
    expect(again(12, waking)).toBe(false);
    expect(again(0, new ApiError(500))).toBe(false);
    expect(wait(0, waking)).toBe(5000);
    expect(wait(0, new Error("x"))).toBe(500);
    expect(wait(1, new Error("x"))).toBe(1000);
  });
});

describe("a network that drops and comes back", () => {
  afterEach(() => {
    onlineManager.setOnline(true);
  });

  it("asks nothing again when the browser is back online: every request moves the idle clocks", async () => {
    let calls = 0;
    server.use(
      http.get("*/api/v1/session", () => {
        calls += 1;
        return HttpResponse.json(session);
      }),
    );
    const client = createQueryClient();
    // As the app's provider does: the client listens to the browser going offline and online.
    client.mount();
    // Stale at once, so only the reconnect rule decides whether it is asked again.
    const observer = new QueryObserver(client, { ...sessionQuery, staleTime: 0 });
    const unsubscribe = observer.subscribe(() => undefined);
    await expect.poll(() => calls).toBe(1);
    for (let i = 0; i < 3; i += 1) {
      onlineManager.setOnline(false);
      onlineManager.setOnline(true);
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(calls).toBe(1);
    expect(client.getDefaultOptions().queries?.refetchOnReconnect).toBe(false);
    unsubscribe();
    client.unmount();
  });
});
