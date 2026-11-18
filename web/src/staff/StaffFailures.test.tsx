import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it } from "vitest";
import { MOCK_EMAILS, MOCK_PIN } from "../mocks/staff";
import { server } from "../test/setup";
import { giveThePin, open, problemAnswer, rowOf } from "./staffTestKit";

afterEach(() => {
  server.events.removeAllListeners();
});

async function fillInvite() {
  await userEvent.type(await screen.findByLabelText("Email"), "x@example.com");
  await userEvent.selectOptions(screen.getByLabelText("Facility"), "ph-demo");
  await userEvent.click(screen.getByRole("button", { name: "Invite" }));
}

const revokeButton = async () =>
  (await rowOf("Paolo Cruz")).getByRole("button", { name: "Revoke Paolo Cruz's access" });

describe("the words about the list", () => {
  it("says one locked PIN in the singular", async () => {
    await open(MOCK_EMAILS.admin);
    expect(await screen.findByText("1 PIN is locked. It's at the top.")).toBeVisible();
  });
});

describe("a PIN never stays in the mutation cache", () => {
  it.each([
    [
      "an invite",
      async () => {
        await fillInvite();
        await giveThePin(/^Invite /, "Send invite");
      },
      "x@example.com",
    ],
    [
      "a revoke",
      async () => {
        await userEvent.click(await revokeButton());
        await giveThePin("Revoke Paolo Cruz's access?", "Revoke access");
      },
      "Paolo Cruz",
    ],
    [
      "a reset",
      async () => {
        await userEvent.click(
          (await rowOf("Lito Santos")).getByRole("button", { name: "Reset PIN for Lito Santos" }),
        );
        await giveThePin("Reset Lito Santos's PIN?", "Reset PIN");
      },
      "Lito Santos",
    ],
  ])("after %s", async (_name, act, seen) => {
    const { queryClient } = await open(MOCK_EMAILS.admin);
    await act();
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
    await rowOf(seen);
    const kept = queryClient.getMutationCache().getAll();
    expect(JSON.stringify(kept.map((m) => m.state))).not.toContain(MOCK_PIN);
    expect(kept).toHaveLength(0);
  });
});

describe("when an action fails", () => {
  it("keeps the dialog with the connection words when there is no connection", async () => {
    await open(MOCK_EMAILS.admin, "/staff", [
      http.post("*/api/v1/users/:id/revoke", () => HttpResponse.error()),
    ]);
    await userEvent.click(await revokeButton());
    const dialog = await giveThePin("Revoke Paolo Cruz's access?", "Revoke access");
    expect(
      await within(dialog).findByText(
        "Couldn't check your PIN. Check your connection and try again.",
      ),
    ).toBeVisible();
    expect(screen.queryByText(/list has been refreshed/)).toBeNull();
    expect(within(dialog).getByLabelText("Your PIN")).toHaveFocus();
  });

  it("keeps the dialog for a server error too", async () => {
    await open(MOCK_EMAILS.admin, "/staff", [
      http.post("*/api/v1/users/:id/pin-reset", () => problemAnswer(500, "internal_error")),
    ]);
    await userEvent.click(
      (await rowOf("Lito Santos")).getByRole("button", { name: "Reset PIN for Lito Santos" }),
    );
    const dialog = await giveThePin("Reset Lito Santos's PIN?", "Reset PIN");
    expect(await within(dialog).findByText(/Check your connection/)).toBeVisible();
    expect(screen.queryByText(/list has been refreshed/)).toBeNull();
  });

  it("looks at the list again, and only then says so, when the person is no longer there", async () => {
    let lists = 0;
    server.events.on("request:start", ({ request }) => {
      if (request.method === "GET" && request.url.endsWith("/api/v1/users")) lists += 1;
    });
    await open(MOCK_EMAILS.admin, "/staff", [
      http.post("*/api/v1/users/:id/revoke", () => problemAnswer(404, "not_found")),
    ]);
    await rowOf("Paolo Cruz");
    const before = lists;
    await userEvent.click(await revokeButton());
    await giveThePin("Revoke Paolo Cruz's access?", "Revoke access");
    expect(await screen.findByText(/That didn't work\. The list has been refreshed/)).toBeVisible();
    expect(lists).toBeGreaterThan(before);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("says a refused facility in the screen's own words and puts the focus on the facility", async () => {
    await open(MOCK_EMAILS.admin, "/staff", [
      http.post("*/api/v1/users", () =>
        problemAnswer(422, "invalid_request", [
          { field: "body.facility_key", message: "no such facility" },
        ]),
      ),
    ]);
    await fillInvite();
    await giveThePin(/^Invite /, "Send invite");
    expect(await screen.findByText("Choose the facility this nurse works at.")).toBeVisible();
    expect(screen.queryByText("no such facility")).toBeNull();
    await waitFor(() => {
      expect(screen.getByLabelText("Facility")).toHaveFocus();
    });
  });

  it("puts the focus on the first field with a problem when both are refused", async () => {
    await open(MOCK_EMAILS.admin, "/staff", [
      http.post("*/api/v1/users", () =>
        problemAnswer(422, "invalid_request", [
          { field: "body.facility_key", message: "no such facility" },
          { field: "body.email", message: "bad address" },
        ]),
      ),
    ]);
    await fillInvite();
    await giveThePin(/^Invite /, "Send invite");
    expect(await screen.findByText("Enter an email address like name@example.com.")).toBeVisible();
    await waitFor(() => {
      expect(screen.getByLabelText("Email")).toHaveFocus();
    });
  });

  it("keeps the invite dialog when a 422 names no field the form has", async () => {
    await open(MOCK_EMAILS.admin, "/staff", [
      http.post("*/api/v1/users", () => problemAnswer(422, "invalid_request")),
    ]);
    await fillInvite();
    const dialog = await giveThePin(/^Invite /, "Send invite");
    expect(await within(dialog).findByText(/Check your connection/)).toBeVisible();
    expect(screen.queryByText("Enter an email address like name@example.com.")).toBeNull();
  });
});
