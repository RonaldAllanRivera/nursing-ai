import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import { MOCK_EMAILS, MOCK_PIN } from "../mocks/staff";
import { holdNote, readHeldNote } from "../notes/heldNote";
import type { QueryClient } from "@tanstack/react-query";
import { renderApp } from "../test/render";
import { server } from "../test/setup";
import { chooseAndUnlock, DEMO_PIN, demoPinHint, signInAsPersona, typePin } from "../test/signIn";
import { DEMO_ENDED, DEMO_EXPIRED, PIN_LOCKED, PIN_WAIT_ENDED, PIN_WEAK } from "./pin";
import { sessionKey, type Session } from "./session";

const SARAH = "Staff nurse · Sarah Navarro, RN";
const head = (gate?: "open" | "set_pin" | "enter_pin" | "pin_locked") => ({
  account: { user: MOCK_EMAILS.phHead, ...(gate ? { gate } : {}) },
});
const newcomer = { account: { user: MOCK_EMAILS.phInvited, gate: "set_pin" as const } };

/** No patient's name, bed or note may be in the page while a gate is up. */
function expectNoPatientData() {
  expect(screen.queryByText(/Demo patient/)).toBeNull();
  expect(within(screen.getByRole("main")).queryAllByRole("link")).toHaveLength(0);
  expect(screen.queryByLabelText("Your note")).toBeNull();
}

describe("enter your PIN", () => {
  it("meets a demo person after sign-in, names her, shows the demo PIN and no patient", async () => {
    await renderApp("/sign-in");
    await userEvent.click(await screen.findByRole("button", { name: SARAH }));
    expect(
      await screen.findByRole("heading", { name: "Enter your PIN, Sarah Navarro, RN" }),
    ).toBeVisible();
    expect(screen.getByText(demoPinHint())).toBeVisible();
    expect(screen.getByLabelText("PIN")).toHaveFocus();
    // The field points at the hint, as every other PIN prompt's field does.
    expect(screen.getByLabelText("PIN")).toHaveAccessibleDescription(
      expect.stringContaining("Demo PIN: 135790"),
    );
    expectNoPatientData();
  });

  it("keeps the header and replaces the page; a right PIN brings the page back", async () => {
    await renderApp("/sign-in");
    await userEvent.click(await screen.findByRole("button", { name: SARAH }));
    await screen.findByLabelText("PIN");
    expect(screen.getByRole("banner")).toHaveTextContent("Sarah Navarro, RN");
    expect(screen.getByRole("button", { name: "Switch nurse" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Sign out" })).toBeNull();
    await typePin(DEMO_PIN);
    expect(await screen.findByRole("heading", { name: "Patients on this ward" })).toBeVisible();
    expect(screen.queryByLabelText("PIN")).toBeNull();
  });

  it("says how many tries are left after a wrong PIN, and empties the field", async () => {
    await renderApp("/sign-in");
    await userEvent.click(await screen.findByRole("button", { name: SARAH }));
    await typePin("999999");
    expect(await screen.findByText("Wrong PIN. 4 tries left.")).toBeVisible();
    const field = screen.getByLabelText("PIN");
    expect(field).toHaveValue("");
    expect(field).toHaveFocus();
    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(field).toHaveAccessibleDescription(expect.stringContaining("Wrong PIN. 4 tries left."));
    expectNoPatientData();
  });

  it("is a masked, numeric, digits-only field of at most six", async () => {
    await renderApp("/sign-in");
    await userEvent.click(await screen.findByRole("button", { name: SARAH }));
    const field = await screen.findByLabelText("PIN");
    expect(field).toHaveAttribute("type", "password");
    expect(field).toHaveAttribute("inputmode", "numeric");
    expect(field).toHaveAttribute("autocomplete", "off");
    expect(field).toHaveAttribute("maxlength", "6");
    await userEvent.type(field, "12ab34-5678");
    expect(field).toHaveValue("123456");
  });

  it("asks for six digits without sending anything when fewer were typed", async () => {
    let sent = 0;
    await renderApp("/sign-in", {}, [
      http.post("*/api/v1/session/unlock", () => {
        sent += 1;
        return HttpResponse.json({}, { status: 500 });
      }),
    ]);
    await userEvent.click(await screen.findByRole("button", { name: SARAH }));
    await typePin("12");
    expect(await screen.findByText("A PIN is 6 digits, 0 to 9.")).toBeVisible();
    expect(sent).toBe(0);
  });

  it("warns on the last try that another wrong PIN ends the demo session", async () => {
    await renderApp("/sign-in");
    await userEvent.click(await screen.findByRole("button", { name: SARAH }));
    for (let i = 0; i < 3; i += 1) await typePin("999999");
    await screen.findByText("Wrong PIN. 2 tries left.");
    await typePin("999999");
    expect(
      await screen.findByText("Wrong PIN. 1 try left. Another wrong PIN ends this demo session."),
    ).toBeVisible();
  });

  it("sends a demo person back to sign-in, saying why, after the fifth wrong PIN", async () => {
    await renderApp("/sign-in");
    await userEvent.click(await screen.findByRole("button", { name: SARAH }));
    for (let i = 0; i < 5; i += 1) await typePin("999999");
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeVisible();
    expect(screen.getByText(DEMO_ENDED)).toBeVisible();
    expect(screen.queryByText(/999999/)).toBeNull();
    // Choosing a person starts again and drops the explanation.
    await userEvent.click(await screen.findByRole("button", { name: SARAH }));
    expect(await screen.findByRole("heading", { name: /Enter your PIN/ })).toBeVisible();
    expect(screen.queryByText(DEMO_ENDED)).toBeNull();
  });

  it("does not show the demo PIN to a Google user, and takes her own PIN", async () => {
    await renderApp("/patients", head());
    expect(await screen.findByRole("heading", { name: /^Enter your PIN, / })).toBeVisible();
    expect(screen.queryByText(/Demo PIN/)).toBeNull();
    await typePin(MOCK_PIN);
    expect(await screen.findByRole("heading", { name: "Patients on this ward" })).toBeVisible();
  });

  it("locks a Google user's PIN on the fifth wrong try, with nothing left to type", async () => {
    await renderApp("/patients", head());
    await screen.findByLabelText("PIN");
    await typePin("999999");
    await screen.findByText("Wrong PIN. 4 tries left.");
    for (let i = 0; i < 3; i += 1) await typePin("999999");
    // A Google user's last try says what one more wrong PIN costs her.
    expect(
      await screen.findByText(
        "Wrong PIN. 1 try left. Another wrong PIN locks it until a head nurse or the admin resets it.",
      ),
    ).toBeVisible();
    await typePin("999999");
    expect(await screen.findByText(PIN_LOCKED)).toBeVisible();
    expect(screen.queryByLabelText("PIN")).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.getByRole("banner")).toBeVisible();
    expectNoPatientData();
  });
});

describe("the other gates", () => {
  it("shows the locked screen for a PIN that was locked already", async () => {
    await renderApp("/patients", head("pin_locked"));
    expect(await screen.findByText(PIN_LOCKED)).toBeVisible();
    expectNoPatientData();
  });

  it("words an idle lock with its minutes and takes the same PIN", async () => {
    const { queryClient } = await renderApp("/patients", head("open"));
    await screen.findByRole("heading", { name: "Patients on this ward" });
    act(() => {
      queryClient.setQueryData<Session | null>(sessionKey, (s) =>
        s ? { ...s, gate: "idle_locked" } : s,
      );
    });
    expect((await screen.findAllByText("Locked after 5 minutes without use.")).length).toBe(1);
    expectNoPatientData();
  });

  it("sets a PIN typed twice: a mismatch is caught before anything is sent", async () => {
    let sent = 0;
    await renderApp("/patients", newcomer, [
      http.post("*/api/v1/session/pin", () => {
        sent += 1;
        return HttpResponse.json({}, { status: 500 });
      }),
    ]);
    expect(await screen.findByRole("heading", { name: /^Choose a PIN, / })).toBeVisible();
    expect(screen.getByText(/until you choose a PIN\./)).toBeVisible();
    expectNoPatientData();
    await userEvent.type(screen.getByLabelText("New PIN"), "135792");
    await userEvent.type(screen.getByLabelText("Type it again"), "135793{Enter}");
    expect(await screen.findByText("The two PINs don't match.")).toBeVisible();
    expect(screen.getByLabelText("Type it again")).toHaveAccessibleDescription(
      "The two PINs don't match.",
    );
    expect(sent).toBe(0);
  });

  it("says a weak PIN in the screen's words on the first field, and clears both", async () => {
    await renderApp("/patients", newcomer);
    await userEvent.type(await screen.findByLabelText("New PIN"), "111111");
    await userEvent.type(screen.getByLabelText("Type it again"), "111111{Enter}");
    expect(await screen.findByText(PIN_WEAK)).toBeVisible();
    // The mock answers in the server's own words; the screen never shows them.
    expect(screen.queryByText(/too easy/)).toBeNull();
    expect(screen.getByLabelText("New PIN")).toHaveAccessibleDescription(
      expect.stringContaining(PIN_WEAK),
    );
    expect(screen.getByLabelText("New PIN")).toHaveValue("");
    expect(screen.getByLabelText("Type it again")).toHaveValue("");
    expect(screen.getByLabelText("New PIN")).toHaveFocus();
  });

  it("signs her out, saying why, when the first PIN came after the idle-lock time since sign-in", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    try {
      await renderApp("/patients", newcomer);
      await userEvent.type(await screen.findByLabelText("New PIN"), "135792");
      // She walked away before the second field: the mock's idle clock ran out meanwhile.
      vi.setSystemTime(Date.now() + 300 * 1000);
      await userEvent.type(screen.getByLabelText("Type it again"), "135792{Enter}");
      expect(await screen.findByRole("heading", { name: "Sign in" })).toBeVisible();
      expect(screen.getByText(PIN_WAIT_ENDED)).toBeVisible();
    } finally {
      vi.useRealTimers();
    }
  });

  it("saves a good PIN and shows the page", async () => {
    await renderApp("/patients", newcomer);
    await userEvent.type(await screen.findByLabelText("New PIN"), "135792");
    await userEvent.type(screen.getByLabelText("Type it again"), "135792{Enter}");
    expect(await screen.findByRole("heading", { name: "Patients on this ward" })).toBeVisible();
  });
});

describe("the page comes back as it was", () => {
  it("keeps the rough note she was typing while a gate replaced the page", async () => {
    const { queryClient } = await signInAsPersona(SARAH);
    expect(await screen.findByRole("heading", { name: "Patients on this ward" })).toBeVisible();
    await userEvent.click(await screen.findByRole("link", { name: /Demo patient A/ }));
    const box = await screen.findByLabelText("Your note");
    await userEvent.click(box);
    await userEvent.paste("pt c/o hilo since 2am");
    // Saving is refused: the server wants the PIN again (an idle lock).
    server.use(
      http.post("*/api/v1/patients/:id/rough-notes", () =>
        HttpResponse.json(
          { type: "about:blank", title: "Locked", status: 423, code: "idle_locked" },
          { status: 423, headers: { "Content-Type": "application/problem+json" } },
        ),
      ),
      http.post("*/api/v1/session/unlock", () =>
        HttpResponse.json({ ...queryClient.getQueryData<Session>(sessionKey), gate: "open" }),
      ),
    );
    await userEvent.click(screen.getByRole("button", { name: "Save note" }));
    expect(await screen.findByRole("heading", { name: /^Enter your PIN/ })).toBeVisible();
    expect(screen.queryByLabelText("Your note")).toBeNull();
    expect(screen.queryByText(/pt c\/o hilo/)).toBeNull();
    expectNoPatientData();
    await typePin(DEMO_PIN);
    const back = await screen.findByLabelText("Your note");
    expect(back).toHaveValue("pt c/o hilo since 2am");
    // The cursor is back where it was (on Save note, which she had pressed), not lost to the top of the page.
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Save note" })).toHaveFocus();
    });
    expect(localStorage.length + sessionStorage.length).toBe(0);
  });

  it("puts the cursor back in the note box when the gate came while she was typing in it", async () => {
    const { queryClient } = await signInAsPersona(SARAH);
    await userEvent.click(await screen.findByRole("link", { name: /Demo patient A/ }));
    const box = await screen.findByLabelText("Your note");
    await userEvent.click(box);
    await userEvent.paste("still typing");
    act(() => {
      queryClient.setQueryData<Session | null>(sessionKey, (s) =>
        s ? { ...s, gate: "idle_locked" } : s,
      );
    });
    await screen.findByRole("heading", { name: /^Enter your PIN/ });
    server.use(
      http.post("*/api/v1/session/unlock", () =>
        HttpResponse.json({ ...queryClient.getQueryData<Session>(sessionKey), gate: "open" }),
      ),
    );
    await typePin(DEMO_PIN);
    const back = await screen.findByLabelText("Your note");
    expect(back).toHaveValue("still typing");
    await waitFor(() => {
      expect(back).toHaveFocus();
    });
  });

  it("drops a held note on sign-out", async () => {
    const { queryClient } = await signInAsPersona(SARAH);
    await screen.findByRole("heading", { name: "Patients on this ward" });
    holdNote(queryClient, "p1", "unsent");
    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
    await screen.findByRole("heading", { name: "Sign in" });
    expect(readHeldNote(queryClient, "p1")).toBe("");
  });

  it("drops a held note when another person signs in", async () => {
    const { queryClient, router } = await signInAsPersona(SARAH);
    await screen.findByRole("heading", { name: "Patients on this ward" });
    holdNote(queryClient, "p1", "unsent");
    await router.navigate({ to: "/sign-in" });
    await chooseAndUnlock("Staff nurse · Emily Carter, RN");
    await screen.findByRole("heading", { name: "Patients on this unit" });
    expect(readHeldNote(queryClient, "p1")).toBe("");
  });

  it("drops a held note on a 401", async () => {
    const { queryClient } = await signInAsPersona(SARAH);
    await screen.findByRole("heading", { name: "Patients on this ward" });
    holdNote(queryClient, "p1", "unsent");
    server.use(
      http.get("*/api/v1/facilities/:key", () =>
        HttpResponse.json(
          { type: "about:blank", title: "Not signed in", status: 401, code: "not_signed_in" },
          { status: 401 },
        ),
      ),
    );
    await act(() => queryClient.invalidateQueries({ queryKey: ["facility"] }));
    await waitFor(() => {
      expect(readHeldNote(queryClient, "p1")).toBe("");
    });
  });

  it("signs a second person in through the PIN too", async () => {
    await renderApp("/sign-in");
    await chooseAndUnlock("Staff nurse · Emily Carter, RN");
    expect(await screen.findByRole("heading", { name: "Patients on this unit" })).toBeVisible();
  });
});

const PATIENT_A = "00000000-0000-4000-8000-000000000011";
const problemJson = (status: number, code: string) =>
  HttpResponse.json(
    { type: "about:blank", title: "x", status, code },
    { status, headers: { "Content-Type": "application/problem+json" } },
  );

/** Mutations in the cache that still hold one of these PINs as their variables. */
function mutationsHolding(queryClient: QueryClient, pins: string[]) {
  return queryClient
    .getMutationCache()
    .getAll()
    .filter((m) => pins.some((pin) => JSON.stringify(m.state.variables ?? null).includes(pin)));
}

describe("a PIN lives only in the field and the one request", () => {
  it("is not kept in the mutation cache after a wrong try, nor after a right one", async () => {
    const { queryClient } = await renderApp("/sign-in");
    await userEvent.click(await screen.findByRole("button", { name: SARAH }));
    await typePin("999999");
    await screen.findByText("Wrong PIN. 4 tries left.");
    await waitFor(() => {
      expect(mutationsHolding(queryClient, ["999999"])).toEqual([]);
    });
    await typePin(DEMO_PIN);
    await screen.findByRole("heading", { name: "Patients on this ward" });
    await waitFor(() => {
      expect(mutationsHolding(queryClient, ["999999", DEMO_PIN])).toEqual([]);
    });
  });

  it("is not kept after setting a PIN either", async () => {
    const { queryClient } = await renderApp("/patients", newcomer);
    await userEvent.type(await screen.findByLabelText("New PIN"), "135792");
    await userEvent.type(screen.getByLabelText("Type it again"), "135792{Enter}");
    await screen.findByRole("heading", { name: "Patients on this ward" });
    await waitFor(() => {
      expect(mutationsHolding(queryClient, ["135792"])).toEqual([]);
    });
  });
});

describe("the gate and the cursor", () => {
  it("describes the PIN field by whose session it is, and by the idle lock", async () => {
    const { queryClient } = await renderApp("/patients", head("open"));
    await screen.findByRole("heading", { name: "Patients on this ward" });
    act(() => {
      queryClient.setQueryData<Session | null>(sessionKey, (s) =>
        s ? { ...s, gate: "idle_locked" } : s,
      );
    });
    const field = await screen.findByLabelText("PIN");
    expect(field).toHaveAccessibleDescription(
      /Nobody sees a patient until the PIN is entered\..*Locked after 5 minutes without use\./,
    );
  });

  it("puts the cursor on the page when the gate goes and what had it is not back", async () => {
    await renderApp("/sign-in");
    await userEvent.click(await screen.findByRole("button", { name: SARAH }));
    await typePin(DEMO_PIN);
    await screen.findByRole("heading", { name: "Patients on this ward" });
    expect(screen.getByRole("main")).toHaveFocus();
  });
});

describe("one person's data never meets another's", () => {
  it("drops the unsent note and empties the form when a refetch of the session answers another user", async () => {
    const { queryClient } = await signInAsPersona(SARAH);
    await userEvent.click(await screen.findByRole("link", { name: /Demo patient A/ }));
    const box = await screen.findByLabelText("Your note");
    await userEvent.click(box);
    await userEvent.paste("A's unsent text");
    expect(readHeldNote(queryClient, PATIENT_A)).toBe("A's unsent text");
    const mine = queryClient.getQueryData<Session>(sessionKey);
    // Another tab signed in as someone else: the shared cookie now answers as her.
    server.use(
      http.get("*/api/v1/session", () =>
        HttpResponse.json({ ...mine, user_id: "someone-else", display_name: "Emily Carter, RN" }),
      ),
    );
    await act(() => queryClient.invalidateQueries({ queryKey: sessionKey }));
    await waitFor(() => {
      expect(screen.getByLabelText("Your note")).toHaveValue("");
    });
    expect(readHeldNote(queryClient, PATIENT_A)).toBe("");
  });

  it("does not hand a held note to a different user who later owns the form", async () => {
    const { queryClient } = await signInAsPersona(SARAH);
    await screen.findByRole("heading", { name: "Patients on this ward" });
    holdNote(queryClient, PATIENT_A, "A's unsent text");
    const mine = queryClient.getQueryData<Session>(sessionKey);
    queryClient.setQueryData(sessionKey, { ...mine, user_id: "someone-else" });
    expect(readHeldNote(queryClient, PATIENT_A)).toBe("");
  });
});

describe("what a failed PIN request says and does", () => {
  it("says a demo session that ran out is not a fifth wrong PIN", async () => {
    await renderApp("/sign-in", {}, [
      http.post("*/api/v1/session/unlock", () => problemJson(401, "not_signed_in")),
    ]);
    await userEvent.click(await screen.findByRole("button", { name: SARAH }));
    await typePin(DEMO_PIN);
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeVisible();
    expect(screen.getByText(DEMO_EXPIRED)).toBeVisible();
    expect(screen.queryByText(DEMO_ENDED)).toBeNull();
  });

  it("looks at the session again on a 409 instead of stranding her", async () => {
    const { queryClient } = await renderApp("/sign-in");
    await userEvent.click(await screen.findByRole("button", { name: SARAH }));
    await screen.findByLabelText("PIN");
    // Another window opened this session: the server is open now, this tab's copy is not.
    const other = await api.POST("/api/v1/session/unlock", { body: { pin: DEMO_PIN } });
    expect(other.response.status).toBe(200);
    expect(queryClient.getQueryData<Session>(sessionKey)?.gate).toBe("enter_pin");
    // So this unlock is a conflict (409), and the page looks at the session again.
    await typePin(DEMO_PIN);
    expect(await screen.findByRole("heading", { name: "Patients on this ward" })).toBeVisible();
  });

  it("keeps the field still while the check is out, so typed digits are not wiped", async () => {
    let release = () => {};
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    await renderApp("/sign-in", {}, [
      http.post("*/api/v1/session/unlock", async () => {
        await held;
        return problemJson(403, "pin_wrong");
      }),
    ]);
    await userEvent.click(await screen.findByRole("button", { name: SARAH }));
    await typePin("999999");
    const field = screen.getByLabelText("PIN");
    await waitFor(() => {
      expect(field).toHaveAttribute("readonly");
    });
    await userEvent.type(field, "123");
    expect(field).toHaveValue("999999");
    release();
    await waitFor(() => {
      expect(field).not.toHaveAttribute("readonly");
    });
    expect(field).toHaveValue("");
  });
});

describe("a note that was sent", () => {
  it("is no longer held, so coming back to the patient shows an empty box", async () => {
    const { queryClient, router } = await signInAsPersona(SARAH);
    await userEvent.click(await screen.findByRole("link", { name: /Demo patient A/ }));
    const box = await screen.findByLabelText("Your note");
    await userEvent.click(box);
    await userEvent.paste("pt c/o hilo since 2am");
    expect(readHeldNote(queryClient, PATIENT_A)).toBe("pt c/o hilo since 2am");
    await userEvent.click(screen.getByRole("button", { name: "Save note" }));
    await waitFor(() => {
      expect(readHeldNote(queryClient, PATIENT_A)).toBe("");
    });
    await screen.findByRole("heading", { name: "Your note" }, { timeout: 8000 });
    await act(() =>
      router.navigate({ to: "/patients/$patientId", params: { patientId: PATIENT_A } }),
    );
    expect(await screen.findByLabelText("Your note")).toHaveValue("");
  });
});

describe("a new try drops the last try's words", () => {
  it("does not keep the old wrong-PIN message up while the next try is out", async () => {
    let release = () => {};
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    await renderApp("/sign-in");
    await userEvent.click(await screen.findByRole("button", { name: SARAH }));
    await typePin("999999");
    await screen.findByText("Wrong PIN. 4 tries left.");
    server.use(
      http.post("*/api/v1/session/unlock", async () => {
        await held;
        return undefined;
      }),
    );
    await typePin("999999");
    await waitFor(() => {
      expect(screen.getByLabelText("PIN")).toHaveAttribute("readonly");
    });
    expect(screen.queryByText("Wrong PIN. 4 tries left.")).toBeNull();
    expect(screen.getByLabelText("PIN")).not.toHaveAttribute("aria-invalid");
    release();
    expect(await screen.findByText("Wrong PIN. 3 tries left.")).toBeVisible();
  });

  it("does not keep the weak-PIN message up while the next try is out", async () => {
    let release = () => {};
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    await renderApp("/patients", newcomer);
    await userEvent.type(await screen.findByLabelText("New PIN"), "111111");
    await userEvent.type(screen.getByLabelText("Type it again"), "111111{Enter}");
    await screen.findByText(PIN_WEAK);
    server.use(
      http.post("*/api/v1/session/pin", async () => {
        await held;
        return undefined;
      }),
    );
    await userEvent.type(screen.getByLabelText("New PIN"), "135792");
    await userEvent.type(screen.getByLabelText("Type it again"), "135792{Enter}");
    await waitFor(() => {
      expect(screen.getByLabelText("New PIN")).toHaveAttribute("readonly");
    });
    expect(screen.queryByText(PIN_WEAK)).toBeNull();
    expect(screen.getByLabelText("New PIN")).not.toHaveAttribute("aria-invalid");
    release();
    expect(await screen.findByRole("heading", { name: "Patients on this ward" })).toBeVisible();
  });
});
