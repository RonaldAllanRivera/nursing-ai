import { MutationObserver, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse, type HttpHandler } from "msw";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { api } from "../api/client";
import { SignInRefreshedError, unwrap } from "../api/errors";
import { createQueryClient } from "../app/queryClient";
import { demoApi } from "../mocks/demo-api";
import { MOCK_EMAILS, MOCK_PIN } from "../mocks/staff";
import { linesInOrder } from "../notes/trace";
import { giveThePin, open, rowOf } from "../staff/staffTestKit";
import { renderApp } from "../test/render";
import { server } from "../test/setup";
import { PIN_NOT_CHECKED, PIN_WAKING } from "./pin";
import { sessionKey } from "./session";
import { usePinRequest } from "./usePinRequest";

const NOTE_1 = "00000000-0000-4000-8000-000000000015";
const problemAnswer = (status: number, code: string) =>
  HttpResponse.json({ type: "about:blank", title: code, status, code }, { status });
const waking = () => problemAnswer(503, "database_waking");
const unauthorised = () => problemAnswer(401, "not_signed_in");

afterEach(() => {
  server.events.removeAllListeners();
});

/** The production client, with only the 5 s wait before a waking retry dropped. */
function productionClient() {
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({
    ...queryClient.getDefaultOptions(),
    mutations: { ...queryClient.getDefaultOptions().mutations, retryDelay: 0 },
  });
  queryClient.setQueryData(sessionKey, { user_id: "u1", csrf_token: "t", gate: "open" });
  return queryClient;
}

describe("a request that carries a PIN is never retried by itself", () => {
  const sign = async (pin: string) =>
    unwrap(
      await api.POST("/api/v1/notes/{note_id}/sign", {
        params: { path: { note_id: "n1" }, header: { "If-Match": '"v1"' } },
        body: { pin },
      }),
    );

  it.each([
    ["a waking database", waking],
    ["a server error", () => problemAnswer(500, "internal")],
  ])("sends a sign once when the 401 re-check meets %s", async (_name, reread) => {
    const queryClient = productionClient();
    let signs = 0;
    server.use(
      http.post("*/api/v1/notes/:id/sign", () => {
        signs += 1;
        return signs === 1 ? unauthorised() : HttpResponse.json({ ok: true });
      }),
      http.get("*/api/v1/session", reread),
    );
    const observer = new MutationObserver(queryClient, { mutationFn: sign, gcTime: 0 });
    const failure = await observer.mutate("123456").catch((error: unknown) => error);
    expect(signs).toBe(1);
    expect(failure).toBeInstanceOf(SignInRefreshedError);
  });

  it("sends a sign once when the sign itself is answered 503 database_waking", async () => {
    const queryClient = productionClient();
    let signs = 0;
    server.use(
      http.post("*/api/v1/notes/:id/sign", () => {
        signs += 1;
        return waking();
      }),
    );
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => usePinRequest(sign, { onSuccess: () => undefined }), {
      wrapper,
    });
    expect(await result.current.run("123456")).toBe(false);
    await new Promise((resolve) => setTimeout(resolve, 200));
    expect(signs).toBe(1);
  });

  it("sends a unlock once when it is answered 503 database_waking", async () => {
    const queryClient = productionClient();
    let unlocks = 0;
    server.use(
      http.post("*/api/v1/session/unlock", () => {
        unlocks += 1;
        return waking();
      }),
    );
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(
      () =>
        usePinRequest(
          async (pin: string) =>
            unwrap(await api.POST("/api/v1/session/unlock", { body: { pin } })),
          { onSuccess: () => undefined },
        ),
      { wrapper },
    );
    expect(await result.current.run("123456")).toBe(false);
    await new Promise((resolve) => setTimeout(resolve, 200));
    expect(unlocks).toBe(1);
  });
});

describe("every PIN dialog keeps its place and tells the truth when the database is waking", () => {
  const note = () => {
    const found = structuredClone(demoApi.notes[NOTE_1]);
    if (!found) throw new Error("no demo note");
    for (const item of linesInOrder(found.draft)) {
      if (item.status !== "source_found") item.review = "confirmed";
    }
    return found;
  };

  /** Counts the requests that match, and answers them as a waking database. */
  function wakingOn(method: "post" | "put", path: string) {
    const seen = { count: 0 };
    const handler: HttpHandler = http[method](path, () => {
      seen.count += 1;
      return waking();
    });
    return { seen, handler };
  }

  it("the sign dialog", async () => {
    const { seen, handler } = wakingOn("post", "*/api/v1/notes/:id/sign");
    await renderApp(`/notes/${NOTE_1}`, { account: { user: MOCK_EMAILS.phStaff, gate: "open" } }, [
      http.get("*/api/v1/notes/:id", () =>
        HttpResponse.json(note(), { headers: { ETag: '"v1"' } }),
      ),
      handler,
    ]);
    await userEvent.click(await screen.findByRole("button", { name: "Sign note" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("Your PIN"), `${MOCK_PIN}{Enter}`);
    expect(await within(dialog).findByText(PIN_WAKING)).toBeVisible();
    expect(seen.count).toBe(1);
    expect(within(dialog).getByLabelText("Your PIN")).toHaveValue("");
  });

  it("the settings save dialog", async () => {
    const { seen, handler } = wakingOn("put", "*/api/v1/facilities/:key");
    await renderApp("/settings", { account: { user: MOCK_EMAILS.admin, gate: "open" } }, [handler]);
    await userEvent.type(await screen.findByRole("textbox", { name: "Facility name" }), "!");
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Enter your PIN to save these settings",
    });
    await userEvent.type(within(dialog).getByLabelText("Your PIN"), `${MOCK_PIN}{Enter}`);
    expect(await within(dialog).findByText(PIN_WAKING)).toBeVisible();
    expect(seen.count).toBe(1);
  });

  it("the staff action dialog", async () => {
    const { seen, handler } = wakingOn("post", "*/api/v1/users/:id/revoke");
    await open(MOCK_EMAILS.admin, "/staff", [handler]);
    await userEvent.click(
      (await rowOf("Paolo Cruz")).getByRole("button", { name: "Revoke Paolo Cruz's access" }),
    );
    const dialog = await giveThePin("Revoke Paolo Cruz's access?", "Revoke access");
    expect(await within(dialog).findByText(PIN_WAKING)).toBeVisible();
    expect(seen.count).toBe(1);
  });

  it("the invite dialog", async () => {
    const { seen, handler } = wakingOn("post", "*/api/v1/users");
    await open(MOCK_EMAILS.admin, "/staff", [handler]);
    await userEvent.type(await screen.findByLabelText("Email"), "x@example.com");
    await userEvent.selectOptions(screen.getByLabelText("Facility"), "ph-demo");
    await userEvent.click(screen.getByRole("button", { name: "Invite" }));
    const dialog = await giveThePin(/^Invite /, "Send invite");
    expect(await within(dialog).findByText(PIN_WAKING)).toBeVisible();
    expect(seen.count).toBe(1);
  });

  it("the PIN screen after sign-in", async () => {
    const { seen, handler } = wakingOn("post", "*/api/v1/session/unlock");
    await renderApp("/patients", { account: { user: MOCK_EMAILS.phStaff, gate: "enter_pin" } }, [
      handler,
    ]);
    await userEvent.type(await screen.findByLabelText("PIN"), `${MOCK_PIN}{Enter}`);
    expect(await screen.findByText(PIN_WAKING)).toBeVisible();
    expect(seen.count).toBe(1);
  });

  it("the choose-a-PIN screen", async () => {
    const { seen, handler } = wakingOn("post", "*/api/v1/session/pin");
    await renderApp("/patients", { account: { user: MOCK_EMAILS.phInvited, gate: "set_pin" } }, [
      handler,
    ]);
    await userEvent.type(await screen.findByLabelText("New PIN"), "135792");
    await userEvent.type(screen.getByLabelText("Type it again"), "135792{Enter}");
    expect(await screen.findByText(PIN_WAKING)).toBeVisible();
    expect(seen.count).toBe(1);
  });

  it("and a 500 on the re-check says to enter the PIN again, not a server error", async () => {
    let signs = 0;
    await renderApp(`/notes/${NOTE_1}`, { account: { user: MOCK_EMAILS.phStaff, gate: "open" } }, [
      http.get("*/api/v1/notes/:id", () =>
        HttpResponse.json(note(), { headers: { ETag: '"v1"' } }),
      ),
      http.post("*/api/v1/notes/:id/sign", () => {
        signs += 1;
        return unauthorised();
      }),
    ]);
    await userEvent.click(await screen.findByRole("button", { name: "Sign note" }));
    const dialog = await screen.findByRole("dialog");
    server.use(http.get("*/api/v1/session", () => problemAnswer(500, "internal")));
    await userEvent.type(within(dialog).getByLabelText("Your PIN"), `${MOCK_PIN}{Enter}`);
    expect(await within(dialog).findByText(PIN_NOT_CHECKED)).toBeVisible();
    await waitFor(() => {
      expect(signs).toBe(1);
    });
  });
});
