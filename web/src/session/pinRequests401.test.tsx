import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it } from "vitest";
import { api } from "../api/client";
import { SignInRefreshedError } from "../api/errors";
import { createQueryClient } from "../app/queryClient";
import { demoApi } from "../mocks/demo-api";
import { MOCK_EMAILS, MOCK_PIN } from "../mocks/staff";
import { holdNote, readHeldNote } from "../notes/heldNote";
import { linesInOrder } from "../notes/trace";
import { giveThePin, open, rowOf } from "../staff/staffTestKit";
import { renderApp } from "../test/render";
import { signInAsPersona } from "../test/signIn";
import { server } from "../test/setup";
import { PIN_NOT_CHECKED } from "./pin";
import { sessionKey, type Session } from "./session";

const SARAH = "Staff nurse · Sarah Navarro, RN";
const PATIENT_A = "00000000-0000-4000-8000-000000000011";
const NOTE_1 = "00000000-0000-4000-8000-000000000015";
const unauthorised = () =>
  HttpResponse.json(
    { type: "about:blank", title: "Sign in", status: 401, code: "not_signed_in" },
    { status: 401 },
  );

afterEach(() => {
  server.events.removeAllListeners();
});

describe("a session re-read that fails some other way does not sign her out", () => {
  it.each([500, 503])("stays signed in when the re-read answers %i", async (status) => {
    const { queryClient } = await signInAsPersona(SARAH);
    await screen.findByRole("heading", { name: "Patients on this ward" });
    holdNote(queryClient, PATIENT_A, "unsent words");
    server.use(
      http.get("*/api/v1/patients/:id", unauthorised),
      http.get("*/api/v1/session", () => HttpResponse.json({}, { status })),
    );
    await userEvent.click(await screen.findByRole("link", { name: /Demo patient A/ }));
    expect(
      await screen.findByText("This patient did not load. Go back and try again."),
    ).toBeVisible();
    expect(queryClient.getQueryData<Session>(sessionKey)).not.toBeNull();
    expect(readHeldNote(queryClient, PATIENT_A)).toBe("unsent words");
    expect(screen.queryByRole("heading", { name: "Sign in" })).toBeNull();
  });
});

describe("a re-read that names someone else", () => {
  it("lets the identity change clear the last person's data", async () => {
    const { queryClient } = await signInAsPersona(SARAH);
    await screen.findByRole("heading", { name: "Patients on this ward" });
    const mine = queryClient.getQueryData<Session>(sessionKey) as Session;
    holdNote(queryClient, PATIENT_A, "unsent words");
    server.use(
      http.get("*/api/v1/patients/:id", () => {
        return unauthorised();
      }),
      // Another tab signed in as someone else: the shared cookie is hers now.
      http.get("*/api/v1/session", () =>
        HttpResponse.json({ ...mine, user_id: "someone-else", display_name: "Emily Carter, RN" }),
      ),
    );
    await userEvent.click(await screen.findByRole("link", { name: /Demo patient A/ }));
    await waitFor(() => {
      expect(queryClient.getQueryData<Session>(sessionKey)?.user_id).toBe("someone-else");
    });
    expect(readHeldNote(queryClient, PATIENT_A)).toBe("");
  });
});

describe("a 401 answered for a request sent as someone else", () => {
  const sessionOf = (user: string) => ({ user_id: user, csrf_token: "t", gate: "open" }) as never;

  it("retries nothing when the re-read names another person, and counts the request once", async () => {
    const queryClient = createQueryClient();
    queryClient.setQueryData(sessionKey, sessionOf("sarah"));
    let reads = 0;
    server.use(
      http.get("*/api/v1/patients", () => {
        reads += 1;
        return unauthorised();
      }),
      http.get("*/api/v1/session", () => HttpResponse.json(sessionOf("emily"))),
    );
    const failure = await api.GET("/api/v1/patients").catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(SignInRefreshedError);
    expect(reads).toBe(1);
    await waitFor(() => {
      expect(queryClient.getQueryData<Session>(sessionKey)?.user_id).toBe("emily");
    });
  });

  it("does not retry a write as the new person who signed in while it waited", async () => {
    const queryClient = createQueryClient();
    queryClient.setQueryData(sessionKey, sessionOf("sarah"));
    let reads = 0;
    let release = () => {};
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    server.use(
      http.get("*/api/v1/patients", async () => {
        reads += 1;
        await held;
        return unauthorised();
      }),
      http.get("*/api/v1/session", () => HttpResponse.json(sessionOf("emily"))),
    );
    const sent = api.GET("/api/v1/patients").catch((error: unknown) => error);
    await waitFor(() => {
      expect(reads).toBe(1);
    });
    // In this tab Emily signs in while Sarah's request is out.
    queryClient.setQueryData(sessionKey, sessionOf("emily"));
    release();
    expect(await sent).toBeInstanceOf(SignInRefreshedError);
    expect(reads).toBe(1);
  });
});

describe("a request that carries a PIN is never sent twice", () => {
  const note = () => {
    const found = structuredClone(demoApi.notes[NOTE_1]);
    if (!found) throw new Error("no demo note");
    for (const item of linesInOrder(found.draft)) {
      if (item.status !== "source_found") item.review = "confirmed";
    }
    return found;
  };

  it("keeps the sign dialog open with words to enter the PIN again, then sends the next try", async () => {
    let signs = 0;
    await renderApp(`/notes/${NOTE_1}`, { account: { user: MOCK_EMAILS.phStaff, gate: "open" } }, [
      http.get("*/api/v1/notes/:id", () =>
        HttpResponse.json(note(), { headers: { ETag: '"v1"' } }),
      ),
      http.post("*/api/v1/notes/:id/sign", () => {
        signs += 1;
        return signs === 1 ? unauthorised() : undefined;
      }),
    ]);
    await userEvent.click(await screen.findByRole("button", { name: "Sign note" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("Your PIN"), `${MOCK_PIN}{Enter}`);
    expect(await within(dialog).findByText(PIN_NOT_CHECKED)).toBeVisible();
    // The PIN went out once; the dialog is still there, and she is still signed in.
    expect(signs).toBe(1);
    expect(screen.queryByRole("heading", { name: "Sign in" })).toBeNull();
    expect(within(dialog).getByLabelText("Your PIN")).toHaveValue("");
    await userEvent.type(within(dialog).getByLabelText("Your PIN"), `${MOCK_PIN}{Enter}`);
    await waitFor(() => {
      expect(signs).toBe(2);
    });
  });

  it("does the same for a staff action: one request, the dialog stays with the words", async () => {
    let revokes = 0;
    await open(MOCK_EMAILS.admin, "/staff", [
      http.post("*/api/v1/users/:id/revoke", () => {
        revokes += 1;
        return revokes === 1 ? unauthorised() : undefined;
      }),
    ]);
    await userEvent.click(
      (await rowOf("Paolo Cruz")).getByRole("button", { name: "Revoke Paolo Cruz's access" }),
    );
    const dialog = await giveThePin("Revoke Paolo Cruz's access?", "Revoke access");
    expect(await within(dialog).findByText(PIN_NOT_CHECKED)).toBeVisible();
    expect(revokes).toBe(1);
    expect(screen.queryByRole("heading", { name: "Sign in" })).toBeNull();
    await userEvent.type(within(dialog).getByLabelText("Your PIN"), MOCK_PIN);
    await userEvent.click(within(dialog).getByRole("button", { name: "Revoke access" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
    expect(revokes).toBe(2);
    expect((await rowOf("Paolo Cruz")).getByText("Revoked")).toBeVisible();
  });
});
