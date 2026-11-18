import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { MOCK_EMAILS, MOCK_PIN } from "../mocks/staff";
import { holdNote, readHeldNote } from "../notes/heldNote";
import { renderApp } from "../test/render";
import { DEMO_PIN, signInAsPersona, typePin } from "../test/signIn";
import { server } from "../test/setup";
import { patchGate } from "./gate";
import { sessionKey, type Session } from "./session";

const SARAH = "Staff nurse · Sarah Navarro, RN";
const PATIENT_A = "00000000-0000-4000-8000-000000000011";
const unauthorised = () =>
  HttpResponse.json(
    { type: "about:blank", title: "Sign in", status: 401, code: "not_signed_in" },
    { status: 401 },
  );

describe("a 401 is checked once before it signs anyone out", () => {
  it("keeps her signed in when the session re-read is caught by the unlock's new token", async () => {
    const { queryClient } = await signInAsPersona(SARAH);
    await screen.findByRole("heading", { name: "Patients on this ward" });
    const mine = queryClient.getQueryData<Session>(sessionKey) as Session;
    holdNote(queryClient, PATIENT_A, "unsent words");
    // The idle lock caught her: the PIN screen shows over the page.
    act(() => {
      patchGate(queryClient, "idle_locked");
    });
    await screen.findByRole("heading", { name: /Enter your PIN/ });

    let finishUnlock = () => {};
    const unlockHeld = new Promise<void>((resolve) => {
      finishUnlock = resolve;
    });
    let sessionReads = 0;
    server.use(
      http.post("*/api/v1/session/unlock", async () => {
        await unlockHeld;
        return HttpResponse.json({ ...mine, gate: "open" });
      }),
      // The re-read that left with the old cookie is refused; the next one has the new cookie.
      http.get("*/api/v1/session", () => {
        sessionReads += 1;
        return sessionReads === 1 ? unauthorised() : HttpResponse.json({ ...mine, gate: "open" });
      }),
    );
    await userEvent.type(await screen.findByLabelText("PIN"), `${DEMO_PIN}{Enter}`);
    void queryClient.invalidateQueries({ queryKey: sessionKey });
    await waitFor(() => {
      expect(sessionReads).toBe(1);
    });
    // The 401 waits for the unlock to settle; nothing has been signed out meanwhile.
    expect(queryClient.getQueryData<Session>(sessionKey)).not.toBeNull();
    finishUnlock();
    await screen.findByRole("heading", { name: "Patients on this ward" });
    expect(queryClient.getQueryData<Session>(sessionKey)?.user_id).toBe(mine.user_id);
    expect(readHeldNote(queryClient, PATIENT_A)).toBe("unsent words");
    expect(screen.queryByRole("heading", { name: "Sign in" })).toBeNull();
    // (The unlock stores its own answer, which cancels the waiting read: no second read is needed.)
  });

  it("asks a data request again once when the session is still there", async () => {
    const { queryClient } = await signInAsPersona(SARAH);
    await screen.findByRole("heading", { name: "Patients on this ward" });
    holdNote(queryClient, PATIENT_A, "unsent words");
    let patientReads = 0;
    server.use(
      http.get("*/api/v1/patients/:id", () => {
        patientReads += 1;
        return patientReads === 1 ? unauthorised() : undefined;
      }),
    );
    await userEvent.click(await screen.findByRole("link", { name: /Demo patient A/ }));
    await screen.findByLabelText("Your note");
    expect(patientReads).toBe(2);
    expect(queryClient.getQueryData<Session>(sessionKey)).not.toBeNull();
    expect(readHeldNote(queryClient, PATIENT_A)).toBe("unsent words");
    expect(screen.queryByRole("heading", { name: "Sign in" })).toBeNull();
  });

  it("signs her out, and promptly, when the re-read also says there is no session", async () => {
    const { queryClient } = await signInAsPersona(SARAH);
    await screen.findByRole("heading", { name: "Patients on this ward" });
    holdNote(queryClient, PATIENT_A, "unsent words");
    let patientReads = 0;
    let sessionReads = 0;
    server.use(
      http.get("*/api/v1/patients/:id", () => {
        patientReads += 1;
        return unauthorised();
      }),
      http.get("*/api/v1/session", () => {
        sessionReads += 1;
        return unauthorised();
      }),
    );
    await userEvent.click(await screen.findByRole("link", { name: /Demo patient A/ }));
    await screen.findByRole("heading", { name: "Sign in" }, { timeout: 4000 });
    // One check per 401: each refused request is followed by at most one session read (an aborted one by none).
    expect(sessionReads).toBeGreaterThan(0);
    expect(sessionReads).toBeLessThanOrEqual(patientReads);
    expect(patientReads).toBeGreaterThan(0);
  });

  it("signs her out at once, with the words, when choosing a first PIN outlived the session", async () => {
    let attempts = 0;
    let sessionReads = 0;
    await renderApp("/patients", { account: { user: MOCK_EMAILS.phInvited, gate: "set_pin" } }, [
      http.post("*/api/v1/session/pin", () => {
        attempts += 1;
        return unauthorised();
      }),
    ]);
    server.use(
      http.get("*/api/v1/session", () => {
        sessionReads += 1;
        return undefined;
      }),
    );
    await userEvent.type(await screen.findByLabelText("New PIN"), MOCK_PIN);
    await userEvent.type(screen.getByLabelText("Type it again"), `${MOCK_PIN}{Enter}`);
    await screen.findByRole("heading", { name: "Sign in" }, { timeout: 4000 });
    expect(
      screen.getByText("Choosing your PIN took too long, so you were signed out. Sign in again."),
    ).toBeVisible();
    expect(attempts).toBe(1);
    expect(sessionReads).toBe(0);
  });

  it("never sends an unlock's PIN twice when the unlock answers 401", async () => {
    let attempts = 0;
    const { queryClient } = await signInAsPersona(SARAH);
    await screen.findByRole("heading", { name: "Patients on this ward" });
    act(() => {
      patchGate(queryClient, "idle_locked");
    });
    server.use(
      http.post("*/api/v1/session/unlock", () => {
        attempts += 1;
        return unauthorised();
      }),
    );
    await typePin(DEMO_PIN);
    await screen.findByRole("heading", { name: "Sign in" }, { timeout: 4000 });
    expect(attempts).toBe(1);
  });
});
