import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import { MOCK_EMAILS, MOCK_PIN } from "../mocks/staff";
import { server } from "../test/setup";
import { pageStatus } from "../test/status";
import { signInAsPersona } from "../test/signIn";
import { giveThePin, open, rowOf } from "./staffTestKit";

afterEach(() => {
  server.events.removeAllListeners();
});

describe("who gets to the Staff screen", () => {
  it("shows the Staff link to a Google admin", async () => {
    await open(MOCK_EMAILS.admin, "/settings");
    expect(await screen.findByRole("link", { name: "Staff" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Settings" })).toBeVisible();
  });

  it("shows a head nurse her Staff link beside Patients", async () => {
    await open(MOCK_EMAILS.phHead, "/patients");
    expect(await screen.findByRole("link", { name: "Staff" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Patients" })).toBeVisible();
  });

  it("sends a staff nurse who opens /staff to her patients, with no Staff link", async () => {
    await open(MOCK_EMAILS.phStaff);
    expect(await screen.findByRole("heading", { name: "Patients on this ward" })).toBeVisible();
    expect(screen.queryByRole("link", { name: "Staff" })).toBeNull();
  });

  it("sends a demo persona who opens /staff away, with no Staff link", async () => {
    const view = await signInAsPersona("Admin · Victor Lazaro");
    await screen.findByRole("heading", { name: "Settings" });
    expect(screen.queryByRole("link", { name: "Staff" })).toBeNull();
    await view.router.navigate({ to: "/staff" });
    expect(await screen.findByRole("heading", { name: "Settings" })).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Staff" })).toBeNull();
  });
});

describe("the staff list", () => {
  it("shows the admin everyone, with a locked PIN first and each person's status in words", async () => {
    await open(MOCK_EMAILS.admin);
    expect(await screen.findByRole("heading", { name: "Staff" })).toBeVisible();
    const items = await screen.findAllByRole("listitem");
    const rows = items.filter((li) => li.closest("ul")?.getAttribute("aria-label") === "Staff");
    expect(rows).toHaveLength(8);
    expect(within(rows[0] as HTMLElement).getByText("Lito Santos")).toBeVisible();
    expect(within(rows[0] as HTMLElement).getByText("PIN locked")).toBeVisible();
    const irene = await rowOf("Irene Lim");
    expect(irene.getByText("Invited")).toBeVisible();
    expect(irene.getByText("irene.lim@example.com")).toBeVisible();
    expect((await rowOf("Rita Moore")).getByText("Revoked")).toBeVisible();
    expect((await rowOf("Paolo Cruz")).getByText("Active")).toBeVisible();
    expect((await rowOf("Paolo Cruz")).getByText("Staff nurse")).toBeVisible();
    expect(screen.getAllByText("SYNTHETIC Demo Hospital (US)").length).toBeGreaterThan(0);
  });

  it("shows a head nurse her own facility only, with no invite form", async () => {
    await open(MOCK_EMAILS.phHead);
    await screen.findByText("Lito Santos");
    expect(screen.queryByText("Rita Moore")).toBeNull();
    expect(screen.queryByText("Sam Porter")).toBeNull();
    expect(screen.queryByText("Dana Admin")).toBeNull();
    expect(screen.queryByRole("heading", { name: "Invite someone" })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Revoke/ })).toBeNull();
  });

  it("offers each row only what the actor may do", async () => {
    await open(MOCK_EMAILS.admin);
    const dana = await rowOf("Dana Admin");
    expect(dana.queryByRole("button")).toBeNull();
    const irene = await rowOf("Irene Lim");
    expect(irene.getByRole("button", { name: "Revoke Irene Lim's access" })).toBeVisible();
    expect(irene.queryByRole("button", { name: /Reset PIN/ })).toBeNull();
    expect((await rowOf("Rita Moore")).queryByRole("button")).toBeNull();
    const paolo = await rowOf("Paolo Cruz");
    expect(paolo.getByRole("button", { name: "Reset PIN for Paolo Cruz" })).toBeVisible();
  });

  it("gives a head nurse Reset PIN on her staff and none on herself", async () => {
    await open(MOCK_EMAILS.phHead);
    expect(
      (await rowOf("Lito Santos")).getByRole("button", { name: "Reset PIN for Lito Santos" }),
    ).toBeVisible();
    expect((await rowOf("Hana Reyes")).queryByRole("button")).toBeNull();
  });
});

describe("inviting", () => {
  it("checks the form before asking for a PIN", async () => {
    await open(MOCK_EMAILS.admin);
    await userEvent.click(await screen.findByRole("button", { name: "Invite" }));
    expect(await screen.findByText("Enter an email address like name@example.com.")).toBeVisible();
    expect(screen.getByText("Choose the facility this nurse works at.")).toBeVisible();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByLabelText("Email")).toHaveFocus();
  });

  it("asks for the PIN, then shows the person as invited with the email in lower case, and clears the form", async () => {
    await open(MOCK_EMAILS.admin);
    await userEvent.type(await screen.findByLabelText("Email"), "New.Nurse@Example.com");
    await userEvent.selectOptions(screen.getByLabelText("Facility"), "us-demo");
    await userEvent.click(screen.getByRole("button", { name: "Invite" }));
    await giveThePin("Invite New.Nurse@Example.com?", "Send invite");
    const row = await rowOf("new.nurse@example.com");
    expect(row.getByText("Invited")).toBeVisible();
    expect(pageStatus()).toHaveTextContent("new.nurse@example.com is invited.");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByLabelText("Email")).toHaveValue("");
    expect(screen.getByLabelText("Email")).toHaveFocus();
  });

  it("takes no facility for an admin", async () => {
    await open(MOCK_EMAILS.admin);
    await userEvent.selectOptions(await screen.findByLabelText("Role"), "admin");
    expect(screen.queryByLabelText("Facility")).toBeNull();
    await userEvent.type(screen.getByLabelText("Email"), "second.admin@example.com");
    await userEvent.click(screen.getByRole("button", { name: "Invite" }));
    await giveThePin(/^Invite second.admin@example.com\?/, "Send invite");
    expect((await rowOf("second.admin@example.com")).getByText("Admin")).toBeVisible();
  });

  it("says a taken email is already on the list, and keeps what was typed", async () => {
    await open(MOCK_EMAILS.admin);
    await userEvent.type(await screen.findByLabelText("Email"), MOCK_EMAILS.phStaff.toUpperCase());
    await userEvent.selectOptions(screen.getByLabelText("Facility"), "ph-demo");
    await userEvent.click(screen.getByRole("button", { name: "Invite" }));
    await giveThePin(/^Invite /, "Send invite");
    expect(await screen.findByText("That email is already on the list.")).toBeVisible();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByLabelText("Email")).toHaveValue(MOCK_EMAILS.phStaff.toUpperCase());
    expect(screen.getByLabelText("Email")).toHaveFocus();
  });

  it("says the tries left after a wrong PIN and keeps the dialog", async () => {
    await open(MOCK_EMAILS.admin);
    await userEvent.type(await screen.findByLabelText("Email"), "x@example.com");
    await userEvent.selectOptions(screen.getByLabelText("Facility"), "ph-demo");
    await userEvent.click(screen.getByRole("button", { name: "Invite" }));
    const dialog = await giveThePin(/^Invite /, "Send invite", "999999");
    expect(await within(dialog).findByText(/Wrong PIN\. 4 tries left\./)).toBeVisible();
    expect(within(dialog).getByLabelText("Your PIN")).toHaveValue("");
  });
});

describe("revoking", () => {
  it("names the person, puts the focus on the safe choice, and turns the row to revoked", async () => {
    await open(MOCK_EMAILS.admin);
    const paolo = await rowOf("Paolo Cruz");
    await userEvent.click(paolo.getByRole("button", { name: "Revoke Paolo Cruz's access" }));
    const dialog = await screen.findByRole("dialog", { name: "Revoke Paolo Cruz's access?" });
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
    await userEvent.type(within(dialog).getByLabelText("Your PIN"), MOCK_PIN);
    await userEvent.click(within(dialog).getByRole("button", { name: "Revoke access" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
    const after = await rowOf("Paolo Cruz");
    expect(after.getByText("Revoked")).toBeVisible();
    expect(after.queryByRole("button")).toBeNull();
    expect(pageStatus()).toHaveTextContent("Paolo Cruz's access is revoked.");
  });

  it("says the tries left after a wrong PIN and changes nothing", async () => {
    await open(MOCK_EMAILS.admin);
    await userEvent.click(
      (await rowOf("Paolo Cruz")).getByRole("button", { name: "Revoke Paolo Cruz's access" }),
    );
    const dialog = await giveThePin("Revoke Paolo Cruz's access?", "Revoke access", "111111");
    expect(await within(dialog).findByText(/Wrong PIN\. 4 tries left\./)).toBeVisible();
    expect((await rowOf("Paolo Cruz")).getByText("Active")).toBeVisible();
  });

  it("cancels without sending anything and returns the focus to the button", async () => {
    await open(MOCK_EMAILS.admin);
    const button = (await rowOf("Irene Lim")).getByRole("button", {
      name: "Revoke Irene Lim's access",
    });
    await userEvent.click(button);
    await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    await waitFor(() => {
      expect(button).toHaveFocus();
    });
    expect((await rowOf("Irene Lim")).getByText("Invited")).toBeVisible();
  });
});

describe("resetting a PIN", () => {
  it("lets a head nurse reset a locked PIN: the flag clears, and the dialog says what happens next", async () => {
    await open(MOCK_EMAILS.phHead);
    const lito = await rowOf("Lito Santos");
    expect(lito.getByText("PIN locked")).toBeVisible();
    await userEvent.click(lito.getByRole("button", { name: "Reset PIN for Lito Santos" }));
    const dialog = await screen.findByRole("dialog", { name: "Reset Lito Santos's PIN?" });
    expect(dialog).toHaveTextContent(
      "Ask them to sign in and choose a new PIN now, with you there.",
    );
    expect(within(dialog).getByLabelText("Your PIN")).toHaveFocus();
    await userEvent.type(within(dialog).getByLabelText("Your PIN"), MOCK_PIN);
    await userEvent.click(within(dialog).getByRole("button", { name: "Reset PIN" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
    expect((await rowOf("Lito Santos")).queryByText("PIN locked")).toBeNull();
    expect(pageStatus()).toHaveTextContent("Lito Santos's PIN is reset.");
  });

  it("lets the admin reset an unlocked PIN too", async () => {
    await open(MOCK_EMAILS.admin);
    await userEvent.click(
      (await rowOf("Paolo Cruz")).getByRole("button", { name: "Reset PIN for Paolo Cruz" }),
    );
    await giveThePin("Reset Paolo Cruz's PIN?", "Reset PIN");
    await waitFor(() => {
      expect(pageStatus()).toHaveTextContent("Paolo Cruz's PIN is reset.");
    });
  });

  it("says the tries left after a wrong PIN, and the row keeps its flag", async () => {
    await open(MOCK_EMAILS.phHead);
    await userEvent.click(
      (await rowOf("Lito Santos")).getByRole("button", { name: "Reset PIN for Lito Santos" }),
    );
    const dialog = await giveThePin("Reset Lito Santos's PIN?", "Reset PIN", "111111");
    expect(await within(dialog).findByText(/Wrong PIN\. 4 tries left\./)).toBeVisible();
    expect((await rowOf("Lito Santos")).getByText("PIN locked")).toBeVisible();
  });
});
