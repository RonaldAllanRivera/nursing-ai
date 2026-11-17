import { act, fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import { MOCK_EMAILS, MOCK_PIN } from "../mocks/staff";
import { HELD_NOTE_ROOT, holdNote } from "../notes/heldNote";
import { renderApp } from "../test/render";
import { server } from "../test/setup";

import { sessionEndedWords } from "./expiry";
import { sessionKey, type Session } from "./session";

const MINUTE = 60_000;

beforeEach(() => {
  // The clock moves with the real one too (so findBy works) and jumps when a test says so.
  vi.useFakeTimers({
    shouldAdvanceTime: true,
    toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval", "Date"],
  });
});
afterEach(() => {
  vi.useRealTimers();
  localStorage.clear();
});

/** A head nurse's open session on the patients page. */
async function openPage(user: string = MOCK_EMAILS.phHead) {
  const view = await renderApp("/patients", { account: { user, gate: "open" } });
  await screen.findByRole("heading", { name: /^Patients on this (ward|unit)$/ });
  return view;
}

async function pass(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

/** Counts every `GET /api/v1/session` the app sends. */
function countSessionReads() {
  const counter = { reads: 0 };
  const onStart = ({ request }: { request: Request }) => {
    if (request.method === "GET" && new URL(request.url).pathname === "/api/v1/session") {
      counter.reads += 1;
    }
  };
  server.events.on("request:start", onStart);
  return {
    counter,
    stop: () => {
      server.events.removeListener("request:start", onStart);
    },
  };
}

describe("the browser's own idle lock", () => {
  it("locks after the session's idle seconds and shows the lock screen with no patient", async () => {
    await openPage();
    await pass(299_000);
    expect(screen.queryByLabelText("PIN")).toBeNull();
    await pass(7_000);
    expect(await screen.findByLabelText("PIN")).toBeVisible();
    expect(screen.getByText("Locked after 5 minutes without use.")).toBeVisible();
    expect(screen.queryByText(/Demo patient/)).toBeNull();
  });

  it("starts the count again on a key press or a click, not on a mouse move", async () => {
    await openPage();
    await pass(200_000);
    fireEvent.pointerMove(document.body);
    await pass(99_000);
    // 299 s since the last real activity: a passing hand did not count.
    fireEvent.keyDown(document.body, { key: "a" });
    await pass(250_000);
    expect(screen.queryByLabelText("PIN")).toBeNull();
    await pass(56_000);
    expect(await screen.findByLabelText("PIN")).toBeVisible();
  });

  it("counts a click, a wheel turn and a touch as use", async () => {
    await openPage();
    for (const send of [
      () => fireEvent.pointerDown(document.body),
      () => fireEvent.wheel(document.body),
      () => fireEvent.touchStart(document.body),
    ]) {
      await pass(250_000);
      send();
    }
    expect(screen.queryByLabelText("PIN")).toBeNull();
  });

  it("locks on waking up even when the timer ran late, and a key press then does not save it", async () => {
    await openPage();
    // The machine slept: the clock jumped but no timer ran.
    vi.setSystemTime(Date.now() + 20 * MINUTE);
    fireEvent.keyDown(document.body, { key: "a" });
    expect(await screen.findByLabelText("PIN")).toBeVisible();
  });

  it("locks when the tab becomes visible again after being away too long", async () => {
    await openPage();
    vi.setSystemTime(Date.now() + 20 * MINUTE);
    document.dispatchEvent(new Event("visibilitychange"));
    expect(await screen.findByLabelText("PIN")).toBeVisible();
  });

  it("keeps the typed note across the lock and gives it back after the PIN", async () => {
    await openPage();
    await userEvent.click(await screen.findByRole("link", { name: /Demo patient A/ }));
    const note = await screen.findByLabelText("Your note");
    await userEvent.type(note, "pt c/o hilo");
    await pass(310_000);
    await screen.findByLabelText("PIN");
    expect(screen.queryByLabelText("Your note")).toBeNull();
    expect(screen.queryByText(/Demo patient/)).toBeNull();
    await userEvent.type(screen.getByLabelText("PIN"), `${MOCK_PIN}{Enter}`);
    expect(await screen.findByLabelText("Your note")).toHaveValue("pt c/o hilo");
    expect(screen.getByLabelText("Your note")).toHaveFocus();
  });

  it("does not run while a gate is up, and starts again after the unlock", async () => {
    await openPage();
    await pass(310_000);
    const pin = await screen.findByLabelText("PIN");
    await userEvent.type(pin, `${MOCK_PIN}{Enter}`);
    await screen.findByRole("heading", { name: /^Patients on this (ward|unit)$/ });
    await pass(299_000);
    expect(screen.queryByLabelText("PIN")).toBeNull();
    await pass(8_000);
    expect(await screen.findByLabelText("PIN")).toBeVisible();
  });
});

describe("the browser never locks before the server does", () => {
  const LIST = /^Patients on this (ward|unit)$/;

  it("waits for the server's own clock after a tab comes back, then keeps the lock", async () => {
    const stderr = vi.spyOn(console, "error").mockImplementation(() => undefined);
    await openPage();
    await pass(250_000);
    // Seen again with no click: the read restarts the server's count, so the browser's moves too.
    document.dispatchEvent(new Event("visibilitychange"));
    await pass(500);
    await pass(51_000);
    expect(screen.queryByLabelText("PIN")).toBeNull();
    expect(screen.getByRole("heading", { name: LIST })).toBeVisible();

    // The server would lock at 550 s; the browser follows at 555 s.
    await pass(260_000);
    expect(await screen.findByLabelText("PIN")).toBeVisible();

    // The server is locked too: a wrong PIN is wrong, it does not lift the lock.
    await userEvent.type(screen.getByLabelText("PIN"), "000000{Enter}");
    expect(await screen.findByText(/^Wrong PIN\./)).toBeVisible();
    expect(screen.queryByRole("heading", { name: LIST })).toBeNull();

    // Neither does switching away and back.
    document.dispatchEvent(new Event("visibilitychange"));
    await pass(500);
    expect(screen.getByLabelText("PIN")).toBeVisible();
    expect(screen.queryByRole("heading", { name: LIST })).toBeNull();
    // Nothing threw in a mock handler along the way.
    expect(stderr).not.toHaveBeenCalled();
    stderr.mockRestore();
  });

  it("lifts the lock only with the right PIN after that", async () => {
    await openPage();
    await pass(250_000);
    document.dispatchEvent(new Event("visibilitychange"));
    await pass(310_000);
    await userEvent.type(await screen.findByLabelText("PIN"), `${MOCK_PIN}{Enter}`);
    expect(await screen.findByRole("heading", { name: LIST })).toBeVisible();
  });

  it("is pushed later by a request sent after the last activity, but not by the draft poll", async () => {
    const { queryClient } = await openPage();
    fireEvent.keyDown(document.body, { key: "a" });
    await pass(200_000);
    await act(async () => {
      await queryClient.invalidateQueries({ queryKey: ["patients"] });
    });
    await pass(290_000);
    // 490 s: past 300 s of no activity, but the server was last touched at 200 s.
    expect(screen.queryByLabelText("PIN")).toBeNull();
    await pass(20_000);
    expect(await screen.findByLabelText("PIN")).toBeVisible();
  });

  it("is not pushed by the draft-job poll", async () => {
    await openPage();
    fireEvent.keyDown(document.body, { key: "a" });
    await pass(200_000);
    await api.GET("/api/v1/draft-jobs/{job_id}", { params: { path: { job_id: "a-job" } } });
    await pass(110_000);
    expect(await screen.findByLabelText("PIN")).toBeVisible();
  });
});

describe("the activity heartbeat", () => {
  it("asks for the session on activity once a minute at most, never by itself", async () => {
    await openPage();
    const { counter, stop } = countSessionReads();
    try {
      fireEvent.keyDown(document.body, { key: "a" });
      await pass(10_000);
      fireEvent.keyDown(document.body, { key: "b" });
      expect(counter.reads).toBe(0);
      await pass(55_000);
      fireEvent.pointerDown(document.body);
      await pass(100);
      expect(counter.reads).toBe(1);
      // More use inside the next minute sends nothing.
      await pass(10_000);
      fireEvent.keyDown(document.body, { key: "c" });
      await pass(100);
      expect(counter.reads).toBe(1);
      // Time passing alone sends nothing.
      await pass(200_000);
      expect(counter.reads).toBe(1);
    } finally {
      stop();
    }
  });

  it("keeps the server's idle clock moving with the browser's", async () => {
    await openPage();
    for (let i = 0; i < 6; i++) {
      await pass(65_000);
      fireEvent.keyDown(document.body, { key: "a" });
      await pass(100);
    }
    // Six minutes of use, a request or two each minute: the server never locked it.
    expect(screen.queryByLabelText("PIN")).toBeNull();
    const response = await fetch(`${location.origin}/api/v1/session`);
    expect(((await response.json()) as Session).gate).toBe("open");
  });
});

describe("another tab changes who this tab is", () => {
  it("asks for the session when the tab is visible again and drops the last person's data", async () => {
    const { queryClient } = await openPage();
    const other = queryClient.getQueryData<Session>(sessionKey);
    expect(other).toBeDefined();
    // What the first person has in the cache: a patient she opened and a note she was typing.
    queryClient.setQueryData(["patient", "first-persons-patient"], { name: "kept for her" });
    holdNote(queryClient, "p1", "her unsent words");
    expect(queryClient.getQueryData(["patient", "first-persons-patient"])).toBeDefined();
    expect(queryClient.getQueryData([HELD_NOTE_ROOT, "p1"])).toBeDefined();
    server.use(
      http.get("*/api/v1/session", () =>
        HttpResponse.json({
          ...other,
          user_id: "11111111-1111-4111-8111-111111111111",
          display_name: "Paolo Cruz",
          initials: "PC",
        }),
      ),
    );
    document.dispatchEvent(new Event("visibilitychange"));
    expect(await screen.findByText("Paolo Cruz")).toBeVisible();
    expect(screen.queryByText("Hana Reyes")).toBeNull();
    // Gone from the cache itself, not just hidden from the new person.
    expect(queryClient.getQueryData(["patient", "first-persons-patient"])).toBeUndefined();
    expect(queryClient.getQueryData([HELD_NOTE_ROOT, "p1"])).toBeUndefined();
  });
});

describe("a timer clock that pauses while the machine sleeps", () => {
  // Fake timers keep their own clock: moving the system time does not fire a due timer, which is
  // what a timer that did not run during sleep looks like. No visibility event, no activity.
  it("still locks within a tick of waking", async () => {
    await openPage();
    vi.setSystemTime(Date.now() + 20 * MINUTE);
    await pass(16_000);
    expect(await screen.findByLabelText("PIN")).toBeVisible();
  });

  it("still ends the session within a tick of waking past its hours", async () => {
    await openPage();
    vi.setSystemTime(Date.now() + 13 * 60 * MINUTE);
    await pass(16_000);
    expect(await screen.findByText(sessionEndedWords(12))).toBeVisible();
  });

  it("sends no request just to check the clock", async () => {
    await openPage();
    const { counter, stop } = countSessionReads();
    try {
      await pass(200_000);
      expect(counter.reads).toBe(0);
    } finally {
      stop();
    }
  });
});

describe("the session's hard end", () => {
  it("ends it at expires_at with the facility's hours, clears the data and says so on sign-in", async () => {
    const { queryClient } = await openPage();
    await pass(12 * 60 * MINUTE + MINUTE);
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeVisible();
    expect(screen.getByText(sessionEndedWords(12))).toBeVisible();
    expect(screen.queryByText(/Demo patient/)).toBeNull();
    expect(queryClient.getQueryCache().findAll({ queryKey: ["patients"] })).toHaveLength(0);
  });

  it("uses a US facility's 14 hours", async () => {
    await openPage(MOCK_EMAILS.usHead);
    await pass(14 * 60 * MINUTE + MINUTE);
    expect(await screen.findByText(sessionEndedWords(14))).toBeVisible();
  });

  it("uses 12 hours for the admin, who has no facility", async () => {
    await renderApp("/settings", { account: { user: MOCK_EMAILS.admin, gate: "open" } });
    await screen.findByRole("heading", { name: "Settings" });
    await pass(12 * 60 * MINUTE + MINUTE);
    expect(await screen.findByText(sessionEndedWords(12))).toBeVisible();
  });

  it("ends it under a lock screen too, and drops the held note", async () => {
    const { queryClient } = await openPage();
    await pass(310_000);
    await screen.findByLabelText("PIN");
    holdNote(queryClient, "patient-x", "typed words");
    await pass(12 * 60 * MINUTE);
    expect(await screen.findByText(sessionEndedWords(12))).toBeVisible();
    expect(queryClient.getQueryCache().findAll({ queryKey: [HELD_NOTE_ROOT] })).toHaveLength(0);
  });

  it("leads a 401 after the hour to the same message", async () => {
    const { queryClient } = await openPage();
    server.use(
      http.get("*/api/v1/patients", () =>
        HttpResponse.json(
          { type: "about:blank", title: "Sign in", status: 401, code: "not_signed_in" },
          { status: 401 },
        ),
      ),
    );
    vi.setSystemTime(Date.now() + 13 * 60 * MINUTE);
    await act(async () => {
      await queryClient.invalidateQueries({ queryKey: ["patients"] });
    });
    expect(await screen.findByText(sessionEndedWords(12))).toBeVisible();
  });

  it("says nothing about hours when a session ends early", async () => {
    const { queryClient } = await openPage();
    act(() => {
      queryClient.setQueryData(sessionKey, null);
    });
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeVisible();
    expect(screen.queryByText(/session ended after/)).toBeNull();
  });
});
