import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { demoApi } from "../mocks/demo-api";
import { renderApp } from "../test/render";
import { server } from "../test/setup";
import { chooseAndUnlock } from "../test/signIn";
import { linesInOrder } from "./trace";

const NOTE_1 = "00000000-0000-4000-8000-000000000015";
const SARAH = "Staff nurse · Sarah Navarro, RN";
const FOCUS = /^Dizziness with low blood pressure/;

describe("the sign dialog's live text, opening after opening", () => {
  it("starts empty each time it opens, so 'You can sign now.' is heard again", async () => {
    const found = structuredClone(demoApi.notes[NOTE_1]);
    if (!found) throw new Error("no demo note");
    for (const item of linesInOrder(found.draft)) {
      if (item.status !== "source_found") item.review = "confirmed";
    }
    let release = () => {};
    let held = new Promise<void>((resolve) => {
      release = resolve;
    });
    const app = await renderApp("/sign-in");
    await chooseAndUnlock(SARAH);
    await screen.findByRole("heading", { level: 1 });
    server.use(
      http.get("*/api/v1/notes/:id", () => HttpResponse.json(found, { headers: { ETag: '"v1"' } })),
      http.patch("*/api/v1/notes/:id/lines/:line", async () => {
        await held;
        return HttpResponse.json(found, { headers: { ETag: '"v2"' } });
      }),
    );
    await act(() =>
      app.router.navigate({ to: "/notes/$noteId", params: { noteId: NOTE_1 }, search: {} }),
    );
    await screen.findByRole("heading", { name: "Your note" });
    const card = () => within(screen.getByRole("complementary", { name: /came from/ }));
    const writing = () =>
      app.queryClient
        .getMutationCache()
        .getAll()
        .filter((m) => m.state.status === "pending");

    // One slow change settles while the dialog is closed.
    await userEvent.click(screen.getByRole("button", { name: FOCUS }));
    await userEvent.click(card().getByRole("button", { name: "Undo" }));
    await waitFor(() => {
      expect(writing()).toHaveLength(1);
    });
    release();
    await waitFor(() => {
      expect(writing()).toHaveLength(0);
    });

    // A second slow change is under way when she opens Sign.
    held = new Promise<void>((resolve) => {
      release = resolve;
    });
    await userEvent.click(await card().findByRole("button", { name: "Undo" }));
    await waitFor(() => {
      expect(writing()).toHaveLength(1);
    });
    await userEvent.click(screen.getByRole("button", { name: "Sign note" }));
    const dialog = await screen.findByRole("dialog");
    const live = () => dialog.querySelector("#sign-live")?.textContent ?? "";
    expect(dialog.querySelector("#sign-waiting")).toHaveTextContent(/still being saved/i);
    // Nothing is left over from the first opening, so the next words are a change.
    expect(live()).toBe("");
    release();
    await waitFor(() => {
      expect(live()).toBe("You can sign now.");
    });
  }, 20000);
});
