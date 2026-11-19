import { focusManager, onlineManager } from "@tanstack/react-query";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it } from "vitest";
import { demoApi } from "../mocks/demo-api";
import { retryMutation } from "../app/queryClient";
import { renderApp } from "../test/render";
import { chooseAndUnlock, DEMO_PIN } from "../test/signIn";
import { server } from "../test/setup";
import { linesInOrder } from "./trace";

const NOTE_1 = "00000000-0000-4000-8000-000000000015";
const SARAH = "Staff nurse · Sarah Navarro, RN";
const FOCUS = /^Dizziness with low blood pressure/;

afterEach(() => {
  onlineManager.setOnline(true);
  focusManager.setFocused(undefined);
});

describe("a note's writes while the browser is offline", () => {
  it("fails a line write at once, so a sign behind it never waits or goes out by itself", async () => {
    const found = structuredClone(demoApi.notes[NOTE_1]);
    if (!found) throw new Error("no demo note");
    for (const item of linesInOrder(found.draft)) {
      if (item.status !== "source_found") item.review = "confirmed";
    }
    let signs = 0;
    let patches = 0;
    const app = await renderApp("/sign-in");
    await chooseAndUnlock(SARAH);
    await screen.findByRole("heading", { level: 1 });
    server.use(
      http.get("*/api/v1/notes/:id", () => HttpResponse.json(found, { headers: { ETag: '"v1"' } })),
      http.post("*/api/v1/notes/:id/sign", () => {
        signs += 1;
        return HttpResponse.error();
      }),
      http.patch("*/api/v1/notes/:id/lines/:line", () => {
        patches += 1;
        return HttpResponse.error();
      }),
    );
    await act(() =>
      app.router.navigate({ to: "/notes/$noteId", params: { noteId: NOTE_1 }, search: {} }),
    );
    await screen.findByRole("heading", { name: "Your note" });
    act(() => {
      onlineManager.setOnline(false);
    });

    await userEvent.click(screen.getByRole("button", { name: FOCUS }));
    const card = within(screen.getByRole("complementary", { name: /came from/ }));
    await userEvent.click(card.getByRole("button", { name: "Undo" }));
    // Offline the request cannot reach the server. The line write fails at once with the connection words, instead of waiting for the network.
    expect(await screen.findByText(/Check your connection and try again/)).toBeVisible();

    await userEvent.click(screen.getByRole("button", { name: "Sign note" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("Your PIN"), `${DEMO_PIN}{Enter}`);
    await waitFor(() => {
      expect(within(dialog).getByText(/Check your connection/)).toBeVisible();
    });

    const kept = app.queryClient.getMutationCache().getAll();
    expect(kept.filter((m) => m.state.isPaused || m.state.status === "pending")).toEqual([]);
    expect(JSON.stringify(kept.map((m) => m.state.variables))).not.toContain(DEMO_PIN);
    expect(signs).toBeLessThanOrEqual(1);

    // Back online nothing goes out by itself.
    const before = { signs, patches };
    act(() => {
      onlineManager.setOnline(true);
    });
    await new Promise((resolve) => setTimeout(resolve, 300));
    expect({ signs, patches }).toEqual(before);
  }, 20000);

  it("fails a discard at once offline instead of leaving it paused in the note's line of writes", async () => {
    let discards = 0;
    const app = await renderApp("/sign-in");
    await chooseAndUnlock(SARAH);
    await screen.findByRole("heading", { level: 1 });
    server.use(
      http.post("*/api/v1/notes/:id/discard", () => {
        discards += 1;
        return HttpResponse.error();
      }),
    );
    await act(() =>
      app.router.navigate({ to: "/notes/$noteId", params: { noteId: NOTE_1 }, search: {} }),
    );
    await screen.findByRole("heading", { name: "Your note" });
    act(() => {
      onlineManager.setOnline(false);
    });
    await userEvent.click(screen.getByRole("button", { name: "Discard draft" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Discard draft" }));
    expect(await within(dialog).findByText(/Check your connection and try again/)).toBeVisible();
    const kept = app.queryClient.getMutationCache().getAll();
    expect(kept.filter((m) => m.state.isPaused || m.state.status === "pending")).toEqual([]);
    act(() => {
      onlineManager.setOnline(true);
    });
    await new Promise((resolve) => setTimeout(resolve, 300));
    expect(discards).toBe(1);
  }, 20000);

  it("does not send a sign while a line write is still pending, and sends it once that has settled", async () => {
    const found = structuredClone(demoApi.notes[NOTE_1]);
    if (!found) throw new Error("no demo note");
    for (const item of linesInOrder(found.draft)) {
      if (item.status !== "source_found") item.review = "confirmed";
    }
    let signs = 0;
    let waking = true;
    const app = await renderApp("/sign-in");
    await chooseAndUnlock(SARAH);
    await screen.findByRole("heading", { level: 1 });
    // The app's own rule: a waking database is retried.
    app.queryClient.setDefaultOptions({
      ...app.queryClient.getDefaultOptions(),
      mutations: { retry: retryMutation, retryDelay: 1500 },
    });
    server.use(
      http.get("*/api/v1/notes/:id", () => HttpResponse.json(found, { headers: { ETag: '"v1"' } })),
      http.patch("*/api/v1/notes/:id/lines/:line", () => {
        if (waking) {
          return HttpResponse.json(
            { type: "about:blank", title: "w", status: 503, code: "database_waking" },
            { status: 503 },
          );
        }
        return HttpResponse.json(found, { headers: { ETag: '"v2"' } });
      }),
      http.post("*/api/v1/notes/:id/sign", () => {
        signs += 1;
        return HttpResponse.json(found, { headers: { ETag: '"v3"' } });
      }),
    );
    await act(() =>
      app.router.navigate({ to: "/notes/$noteId", params: { noteId: NOTE_1 }, search: {} }),
    );
    await screen.findByRole("heading", { name: "Your note" });
    await userEvent.click(screen.getByRole("button", { name: FOCUS }));
    const card = within(screen.getByRole("complementary", { name: /came from/ }));
    await userEvent.click(card.getByRole("button", { name: "Undo" }));
    await userEvent.click(screen.getByRole("button", { name: "Sign note" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("Your PIN"), `${DEMO_PIN}{Enter}`);
    // The tab goes to the background: the write's retry now waits.
    act(() => {
      focusManager.setFocused(false);
    });
    await new Promise((resolve) => setTimeout(resolve, 300));

    const live = () => dialog.querySelector("#sign-live")?.textContent ?? "";
    const pinField = within(dialog).getByLabelText("Your PIN");
    expect(dialog.querySelector("#sign-waiting")).toHaveTextContent(/still being saved/i);
    // The reason is read with the field, and a held Enter says it in the live region.
    expect(pinField.getAttribute("aria-describedby")).toContain("sign-waiting");
    await userEvent.keyboard("{Enter}");
    await waitFor(() => {
      expect(live()).toMatch(/still being saved/i);
    });
    expect(pinField).toHaveFocus();
    // A held press on Sign keeps the focus on Sign.
    const signButton = within(dialog).getByRole("button", { name: "Sign note" });
    await userEvent.click(signButton);
    expect(signButton).toHaveFocus();
    const waiting = app.queryClient.getMutationCache().getAll();
    expect(JSON.stringify(waiting.map((m) => m.state.variables))).not.toContain(DEMO_PIN);
    expect(waiting.filter((m) => m.state.status === "pending")).toHaveLength(1);
    expect(signs).toBe(0);
    // The PIN waits only in the field.
    expect(within(dialog).getByLabelText("Your PIN")).toHaveValue(DEMO_PIN);

    waking = false;
    act(() => {
      focusManager.setFocused(true);
    });
    await waitFor(
      () => {
        const pending = app.queryClient
          .getMutationCache()
          .getAll()
          .filter((m) => m.state.status === "pending");
        expect(pending).toEqual([]);
      },
      { timeout: 5000 },
    );
    await waitFor(() => {
      expect(live()).toBe("You can sign now.");
    });
    expect(dialog.querySelector("#sign-waiting")).toBeNull();
    expect(signs).toBe(0);
    await userEvent.click(within(dialog).getByRole("button", { name: "Sign note" }));
    await waitFor(() => {
      expect(signs).toBe(1);
    });
    // After the screen settles, exactly one sign went out.
    await new Promise((resolve) => setTimeout(resolve, 400));
    expect(signs).toBe(1);
  }, 30000);

  it("keeps Sign held when the change it waited for fails, and says to check the note", async () => {
    const found = structuredClone(demoApi.notes[NOTE_1]);
    if (!found) throw new Error("no demo note");
    for (const item of linesInOrder(found.draft)) {
      if (item.status !== "source_found") item.review = "confirmed";
    }
    let signs = 0;
    let release = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const app = await renderApp("/sign-in");
    await chooseAndUnlock(SARAH);
    await screen.findByRole("heading", { level: 1 });
    server.use(
      http.get("*/api/v1/notes/:id", () => HttpResponse.json(found, { headers: { ETag: '"v1"' } })),
      http.patch("*/api/v1/notes/:id/lines/:line", async () => {
        await gate;
        return HttpResponse.json(
          { type: "about:blank", title: "x", status: 500, code: "boom" },
          { status: 500 },
        );
      }),
      http.post("*/api/v1/notes/:id/sign", () => {
        signs += 1;
        return HttpResponse.json(found, { headers: { ETag: '"v3"' } });
      }),
    );
    await act(() =>
      app.router.navigate({ to: "/notes/$noteId", params: { noteId: NOTE_1 }, search: {} }),
    );
    await screen.findByRole("heading", { name: "Your note" });
    await userEvent.click(screen.getByRole("button", { name: FOCUS }));
    const card = within(screen.getByRole("complementary", { name: /came from/ }));
    await userEvent.click(card.getByRole("button", { name: "Undo" }));
    await userEvent.click(screen.getByRole("button", { name: "Sign note" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("Your PIN"), DEMO_PIN);
    expect(dialog.querySelector("#sign-waiting")).toHaveTextContent(/still being saved/i);
    release();
    await waitFor(() => {
      expect(dialog.querySelector("#sign-waiting")).toHaveTextContent(/was not saved/i);
    });
    expect(dialog.querySelector("#sign-live")).toHaveTextContent(
      /Close this and check the note before signing/,
    );
    await userEvent.keyboard("{Enter}");
    await userEvent.click(within(dialog).getByRole("button", { name: "Sign note" }));
    await new Promise((resolve) => setTimeout(resolve, 300));
    expect(signs).toBe(0);
    expect(within(dialog).getByRole("button", { name: "Sign note" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
    expect(signs).toBe(0);
  }, 30000);
});
