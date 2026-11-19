import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { MOCK_EMAILS } from "../mocks/staff";
import { holdNote, readHeldNote } from "../notes/heldNote";
import { PIN_LOCKED_NEXT } from "../session/pin";
import { sessionKey, type Session } from "../session/session";
import { renderApp } from "../test/render";

describe("the header during a gate", () => {
  const ACCOUNTS = [
    ["set_pin", MOCK_EMAILS.phInvited],
    ["enter_pin", MOCK_EMAILS.phHead],
    ["pin_locked", MOCK_EMAILS.phLocked],
  ] as const;

  it.each(ACCOUNTS)(
    "at %s names the person and offers Not you? Switch nurse, with no shift picker or links",
    async (gate, user) => {
      await renderApp("/patients", { account: { user, gate } });
      const header = await screen.findByRole("banner");
      await within(header).findByRole("button", { name: "Switch nurse" });
      expect(within(header).getByText("Not you?")).toBeVisible();
      expect(within(header).getByText(/Staff nurse|Head nurse/)).toBeVisible();
      expect(within(header).queryByRole("button", { name: "Sign out" })).toBeNull();
      expect(within(header).queryByRole("button", { name: "Change shift" })).toBeNull();
      expect(within(header).queryByRole("navigation")).toBeNull();
      expect(within(header).queryByRole("link")).toBeNull();
      expect(within(header).getByRole("button", { name: "Night theme" })).toBeVisible();
    },
  );

  it("shows Switch nurse after an idle lock, and Sign out with the links while open", async () => {
    const { queryClient } = await renderApp("/patients", {
      account: { user: MOCK_EMAILS.phHead, gate: "open" },
    });
    const header = await screen.findByRole("banner");
    expect(await within(header).findByRole("button", { name: "Sign out" })).toBeVisible();
    expect(within(header).getByRole("link", { name: "Patients" })).toBeVisible();
    act(() => {
      queryClient.setQueryData<Session | null>(sessionKey, (s) =>
        s ? { ...s, gate: "idle_locked" } : s,
      );
    });
    expect(await within(header).findByRole("button", { name: "Switch nurse" })).toBeVisible();
    expect(within(header).queryByRole("link", { name: "Patients" })).toBeNull();
  });

  it("Switch nurse ends the session, goes to sign-in and leaves no person's data", async () => {
    const { queryClient } = await renderApp("/patients", {
      account: { user: MOCK_EMAILS.phHead, gate: "enter_pin" },
    });
    holdNote(queryClient, "p1", "unsent");
    await userEvent.click(await screen.findByRole("button", { name: "Switch nurse" }));
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeVisible();
    expect(queryClient.getQueryData(sessionKey)).toBeNull();
    expect(readHeldNote(queryClient, "p1")).toBe("");
    expect(
      queryClient.getQueryCache().findAll({ predicate: (q) => q.queryKey[0] === "patients" }),
    ).toHaveLength(0);
  });

  it("tells whoever's PIN is locked what happens next", async () => {
    await renderApp("/patients", { account: { user: MOCK_EMAILS.phLocked, gate: "pin_locked" } });
    expect(await screen.findByText(PIN_LOCKED_NEXT)).toBeVisible();
    expect(PIN_LOCKED_NEXT).toBe("Once it's reset, choose Switch nurse above and sign in again.");
  });
});
