import { onlineManager, type QueryClient } from "@tanstack/react-query";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it } from "vitest";
import { demoApi } from "../mocks/demo-api";
import { MOCK_EMAILS, MOCK_PIN } from "../mocks/staff";
import { linesInOrder } from "../notes/trace";
import { saveFailureText } from "../settings/form";
import { giveThePin, open, rowOf } from "../staff/staffTestKit";
import { renderApp } from "../test/render";
import { PIN_CONNECTION } from "./pin";

const NOTE_1 = "00000000-0000-4000-8000-000000000015";

afterEach(() => {
  onlineManager.setOnline(true);
});

/** The browser says it is offline, and a request it makes anyway fails the way an offline fetch does. */
function goOffline() {
  act(() => {
    onlineManager.setOnline(false);
  });
}

/** Counts the requests to this route, each answered as a fetch with no network. */
function offlineRoute(method: "post" | "put", path: string) {
  const seen = { count: 0 };
  const handler = http[method](path, () => {
    seen.count += 1;
    return HttpResponse.error();
  });
  return { seen, handler };
}

/** Nothing waits in the mutation cache to go out by itself, and the PIN is nowhere in it. */
function nothingWaiting(queryClient: QueryClient) {
  const kept = queryClient.getMutationCache().getAll();
  expect(kept.filter((m) => m.state.isPaused || m.state.status === "pending")).toEqual([]);
  expect(JSON.stringify(kept.map((m) => m.state))).not.toContain(MOCK_PIN);
}

/** Back online, nothing is sent again: the PIN went with the one request that failed. */
async function backOnlineSendsNothing(seen: { count: number }) {
  act(() => {
    onlineManager.setOnline(true);
  });
  await new Promise((resolve) => setTimeout(resolve, 100));
  expect(seen.count).toBe(1);
}

describe("a request that carries a PIN, made while the browser is offline", () => {
  it("the sign dialog fails at once with its connection words, and can be closed", async () => {
    const found = structuredClone(demoApi.notes[NOTE_1]);
    if (!found) throw new Error("no demo note");
    for (const item of linesInOrder(found.draft)) {
      if (item.status !== "source_found") item.review = "confirmed";
    }
    const { seen, handler } = offlineRoute("post", "*/api/v1/notes/:id/sign");
    const { queryClient } = await renderApp(
      `/notes/${NOTE_1}`,
      { account: { user: MOCK_EMAILS.phStaff, gate: "open" } },
      [
        http.get("*/api/v1/notes/:id", () =>
          HttpResponse.json(found, { headers: { ETag: '"v1"' } }),
        ),
        handler,
      ],
    );
    await userEvent.click(await screen.findByRole("button", { name: "Sign note" }));
    const dialog = await screen.findByRole("dialog");
    goOffline();
    await userEvent.type(within(dialog).getByLabelText("Your PIN"), `${MOCK_PIN}{Enter}`);
    expect(
      await within(dialog).findByText(
        "That change was not saved. Check your connection and try again.",
      ),
    ).toBeVisible();
    expect(within(dialog).getByRole("button", { name: "Sign note" })).toBeVisible();
    expect(within(dialog).getByLabelText("Your PIN")).toHaveValue("");
    nothingWaiting(queryClient);
    await userEvent.keyboard("{Escape}");
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
    await backOnlineSendsNothing(seen);
  });

  it("the PIN screen after sign-in fails at once with its connection words", async () => {
    const { seen, handler } = offlineRoute("post", "*/api/v1/session/unlock");
    const { queryClient } = await renderApp(
      "/patients",
      { account: { user: MOCK_EMAILS.phStaff, gate: "enter_pin" } },
      [handler],
    );
    const field = await screen.findByLabelText("PIN");
    goOffline();
    await userEvent.type(field, `${MOCK_PIN}{Enter}`);
    expect(await screen.findByText(PIN_CONNECTION)).toBeVisible();
    expect(field).toHaveValue("");
    nothingWaiting(queryClient);
    await backOnlineSendsNothing(seen);
  });

  it("a staff action fails at once with its connection words, and can be closed", async () => {
    const { seen, handler } = offlineRoute("post", "*/api/v1/users/:id/revoke");
    const { queryClient } = await open(MOCK_EMAILS.admin, "/staff", [handler]);
    await userEvent.click(
      (await rowOf("Paolo Cruz")).getByRole("button", { name: "Revoke Paolo Cruz's access" }),
    );
    await screen.findByRole("dialog", { name: "Revoke Paolo Cruz's access?" });
    goOffline();
    const dialog = await giveThePin("Revoke Paolo Cruz's access?", "Revoke access");
    expect(await within(dialog).findByText(PIN_CONNECTION)).toBeVisible();
    nothingWaiting(queryClient);
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
    await backOnlineSendsNothing(seen);
  });

  it("a settings save fails at once, and the form says the connection words", async () => {
    const { seen, handler } = offlineRoute("put", "*/api/v1/facilities/:key");
    const { queryClient } = await renderApp(
      "/settings",
      { account: { user: MOCK_EMAILS.admin, gate: "open" } },
      [handler],
    );
    await userEvent.type(await screen.findByRole("textbox", { name: "Facility name" }), "!");
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Enter your PIN to save these settings",
    });
    goOffline();
    await userEvent.type(within(dialog).getByLabelText("Your PIN"), `${MOCK_PIN}{Enter}`);
    expect(await screen.findByText(saveFailureText(null))).toBeVisible();
    nothingWaiting(queryClient);
    await backOnlineSendsNothing(seen);
  });
});
