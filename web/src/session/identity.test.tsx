import { QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import { api } from "../api/client";
import { createQueryClient } from "../app/queryClient";
import { demoApi } from "../mocks/demo-api";
import { createHandlers } from "../mocks/handlers";
import { MOCK_EMAILS } from "../mocks/staff";
import { holdNote, readHeldNote } from "../notes/heldNote";
import { personaId } from "../test/mockSession";
import { server } from "../test/setup";
import { DEMO_PIN, signInAsPersona, typePin } from "../test/signIn";
import { renderApp } from "../test/render";
import { sessionKey, sessionQuery, useSignIn, type Session } from "./session";

const SARAH = "Staff nurse · Sarah Navarro, RN";
const PATIENT_A = "00000000-0000-4000-8000-000000000011";
const SENTINEL = ["sentinel"] as const;

/** The same session, as another person's (what a shared cookie answers after another tab signs in). */
const asSomeoneElse = (mine: Session | undefined): Session =>
  ({ ...mine, user_id: "someone-else", display_name: "Emily Carter, RN" }) as Session;

describe("one person's data never meets another's, whichever answer brings the new person", () => {
  it("clears it when an unlock answers another person's open session", async () => {
    const { queryClient } = await signInAsPersona(SARAH);
    await userEvent.click(await screen.findByRole("link", { name: /Demo patient A/ }));
    const box = await screen.findByLabelText("Your note");
    await userEvent.click(box);
    await userEvent.paste("A's unsent text");
    queryClient.setQueryData(SENTINEL, "A's data");
    expect(queryClient.getQueryData(["patient", PATIENT_A])).toBeDefined();

    // Another tab signs in as Emily: the shared cookie is hers now, and still at the PIN.
    const emily = await api.POST("/api/v1/session", {
      body: { persona_id: personaId("staff_nurse", "us-demo") },
    });
    expect(emily.response.ok).toBe(true);
    // This tab's next request is answered 423, so it shows the PIN screen for Sarah.
    await act(() => queryClient.invalidateQueries({ queryKey: ["patient", PATIENT_A] }));
    await screen.findByRole("heading", { name: "Enter your PIN, Sarah Navarro, RN" });
    // Behind the lock screen the page's data is already gone (C-4); the typed note stays.
    expect(queryClient.getQueryData(SENTINEL)).toBeUndefined();
    expect(readHeldNote(queryClient, PATIENT_A)).toBe("A's unsent text");
    queryClient.setQueryData(SENTINEL, "A's data");
    // She types the demo PIN (personas share it); the answer is Emily's open session.
    server.use(
      http.post("*/api/v1/session/unlock", () =>
        HttpResponse.json({ ...emily.data, gate: "open" }),
      ),
    );
    await typePin(DEMO_PIN);
    await waitFor(() => {
      expect(queryClient.getQueryData<Session>(sessionKey)?.display_name).toBe("Emily Carter, RN");
    });
    expect(queryClient.getQueryData(SENTINEL)).toBeUndefined();
    expect(queryClient.getQueryData(["patients"])).toBeUndefined();
    expect(queryClient.getQueryData(["patient", PATIENT_A])).toBeUndefined();
    expect(readHeldNote(queryClient, PATIENT_A)).toBe("");
    expect(queryClient.getMutationCache().getAll()).toEqual([]);
    expect(screen.queryByText(/Demo patient A/)).toBeNull();
  });

  it("clears it when setting a PIN answers another person's session", async () => {
    const { queryClient } = await renderApp(
      "/patients",
      { account: { user: MOCK_EMAILS.phInvited, gate: "set_pin" } },
      [
        http.post("*/api/v1/session/pin", () =>
          HttpResponse.json(asSomeoneElse(queryClient.getQueryData<Session>(sessionKey))),
        ),
      ],
    );
    queryClient.setQueryData(SENTINEL, "A's data");
    holdNote(queryClient, PATIENT_A, "A's unsent text");
    await userEvent.type(await screen.findByLabelText("New PIN"), "135792");
    await userEvent.type(screen.getByLabelText("Type it again"), "135792{Enter}");
    await waitFor(() => {
      expect(queryClient.getQueryData<Session>(sessionKey)?.user_id).toBe("someone-else");
    });
    expect(queryClient.getQueryData(SENTINEL)).toBeUndefined();
    expect(readHeldNote(queryClient, PATIENT_A)).toBe("");
  });

  it("clears it when a shift change answers another person's session", async () => {
    const { queryClient } = await signInAsPersona(SARAH);
    await screen.findByRole("heading", { name: "Patients on this ward" });
    queryClient.setQueryData(SENTINEL, "A's data");
    holdNote(queryClient, PATIENT_A, "A's unsent text");
    server.use(
      http.put("*/api/v1/session/shift", () =>
        HttpResponse.json(asSomeoneElse(queryClient.getQueryData<Session>(sessionKey))),
      ),
    );
    await userEvent.click(await screen.findByRole("button", { name: "Change shift" }));
    await userEvent.click(await screen.findByRole("button", { name: /^2-10/ }));
    await waitFor(() => {
      expect(queryClient.getQueryData<Session>(sessionKey)?.user_id).toBe("someone-else");
    });
    expect(queryClient.getQueryData(SENTINEL)).toBeUndefined();
    expect(readHeldNote(queryClient, PATIENT_A)).toBe("");
  });

  it("clears nothing when the answer is the same person's", async () => {
    const { queryClient } = await signInAsPersona(SARAH);
    const header = await screen.findByRole("banner");
    await screen.findByRole("heading", { name: "Patients on this ward" });
    queryClient.setQueryData(SENTINEL, "A's data");
    holdNote(queryClient, PATIENT_A, "A's unsent text");
    await userEvent.click(within(header).getByRole("button", { name: "Change shift" }));
    await userEvent.click(await screen.findByRole("button", { name: /^2-10/ }));
    expect(await within(header).findByText("Shift 2-10")).toBeVisible();
    expect(queryClient.getQueryData(SENTINEL)).toBe("A's data");
    expect(readHeldNote(queryClient, PATIENT_A)).toBe("A's unsent text");
  });

  it("is not undone by a slower answer from before the new person signed in", async () => {
    const queryClient = createQueryClient();
    queryClient.setDefaultOptions({
      queries: { ...queryClient.getDefaultOptions().queries, retry: false },
    });
    server.use(...createHandlers(demoApi, {}));
    const first = await api.POST("/api/v1/session", {
      body: { persona_id: personaId("staff_nurse", "ph-demo") },
    });
    const sarah = first.data;
    queryClient.setQueryData(sessionKey, sarah);
    let release = () => {};
    const slow = new Promise<void>((resolve) => {
      release = resolve;
    });
    // A refetch of the session is out, answered as Sarah, and slow.
    server.use(
      http.get("*/api/v1/session", async () => {
        await slow;
        return HttpResponse.json(sarah);
      }),
    );
    const stale = queryClient.query({ ...sessionQuery, staleTime: 0 }).catch(() => undefined);
    const { result } = renderHook(() => useSignIn(), {
      wrapper: ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
      ),
    });
    await act(() => result.current.mutateAsync(personaId("staff_nurse", "us-demo")));
    release();
    await act(() => stale);
    expect(queryClient.getQueryData<Session>(sessionKey)?.display_name).toBe("Emily Carter, RN");
  });
});
