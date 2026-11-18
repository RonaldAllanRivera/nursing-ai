import { onlineManager } from "@tanstack/react-query";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it } from "vitest";
import { demoApi } from "../mocks/demo-api";
import { renderApp } from "../test/render";
import { chooseAndUnlock, DEMO_PIN } from "../test/signIn";
import { server } from "../test/setup";
import { linesInOrder } from "./trace";

const NOTE_1 = "00000000-0000-4000-8000-000000000015";
const SARAH = "Staff nurse · Sarah Navarro, RN";
const FOCUS = /^Dizziness with low blood pressure/;

afterEach(() => {
  onlineManager.setOnline(true);
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
});
