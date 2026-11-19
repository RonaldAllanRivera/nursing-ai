import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import { afterEach, describe, expect, it } from "vitest";
import { MOCK_EMAILS } from "../mocks/staff";
import { server } from "../test/setup";
import { giveThePin, open, problemAnswer, rowOf } from "./staffTestKit";

afterEach(() => {
  server.events.removeAllListeners();
});

/** A dialog that has just opened has nothing to say about a try that was never made. */
function expectNothingSaid(dialog: HTMLElement) {
  expect(within(dialog).queryByRole("alert")).toBeNull();
  expect(within(dialog).getByLabelText("Your PIN")).not.toHaveAttribute("aria-invalid", "true");
}

async function askToInvite(email: string) {
  const field = await screen.findByLabelText("Email");
  await userEvent.clear(field);
  await userEvent.type(field, email);
  await userEvent.selectOptions(screen.getByLabelText("Facility"), "ph-demo");
  await userEvent.click(screen.getByRole("button", { name: "Invite" }));
}

const closed = () =>
  waitFor(() => {
    expect(screen.queryByRole("dialog")).toBeNull();
  });

describe("a dialog that opens after a failure closed the last one", () => {
  it("is empty after an invite was refused for a taken email", async () => {
    await open(MOCK_EMAILS.admin);
    await askToInvite(MOCK_EMAILS.phStaff);
    await giveThePin(/^Invite /, "Send invite");
    await closed();
    await askToInvite("fresh@example.com");
    expectNothingSaid(await screen.findByRole("dialog", { name: /^Invite / }));
  });

  it("is empty after an invite was refused for a field", async () => {
    await open(MOCK_EMAILS.admin, "/staff", [
      http.post(
        "*/api/v1/users",
        () =>
          problemAnswer(422, "invalid_request", [
            { field: "body.facility_key", message: "no such facility" },
          ]),
        { once: true },
      ),
    ]);
    await askToInvite("x@example.com");
    await giveThePin(/^Invite /, "Send invite");
    await closed();
    await userEvent.click(screen.getByRole("button", { name: "Invite" }));
    expectNothingSaid(await screen.findByRole("dialog", { name: /^Invite / }));
  });

  it("is empty after a revoke found the list out of date", async () => {
    await open(MOCK_EMAILS.admin, "/staff", [
      http.post("*/api/v1/users/:id/revoke", () => problemAnswer(404, "not_found")),
    ]);
    await userEvent.click(
      (await rowOf("Paolo Cruz")).getByRole("button", { name: "Revoke Paolo Cruz's access" }),
    );
    await giveThePin("Revoke Paolo Cruz's access?", "Revoke access");
    await screen.findByText(/The list has been refreshed/);
    await userEvent.click(
      (await rowOf("Lito Santos")).getByRole("button", { name: "Reset PIN for Lito Santos" }),
    );
    expectNothingSaid(await screen.findByRole("dialog", { name: "Reset Lito Santos's PIN?" }));
  });

  it("still says a wrong PIN's tries left, and nothing the dialog before it said", async () => {
    await open(MOCK_EMAILS.admin);
    await userEvent.click(
      (await rowOf("Lito Santos")).getByRole("button", { name: "Reset PIN for Lito Santos" }),
    );
    const first = await giveThePin("Reset Lito Santos's PIN?", "Reset PIN", "111111");
    expect(await within(first).findByText(/Wrong PIN\. 4 tries left\./)).toBeVisible();
    await userEvent.click(within(first).getByRole("button", { name: "Cancel" }));
    await closed();
    await userEvent.click(
      (await rowOf("Paolo Cruz")).getByRole("button", { name: "Reset PIN for Paolo Cruz" }),
    );
    expectNothingSaid(await screen.findByRole("dialog", { name: "Reset Paolo Cruz's PIN?" }));
    const second = await giveThePin("Reset Paolo Cruz's PIN?", "Reset PIN", "111111");
    expect(await within(second).findByText(/Wrong PIN\. 3 tries left\./)).toBeVisible();
  });
});
