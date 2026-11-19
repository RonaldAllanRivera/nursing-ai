import { describe, expect, it } from "vitest";
import { inviteBody, validateInvite } from "./invite";
import { inviteWords, resetWords, revokeWords } from "./words";

describe("checking an invitation before the PIN is asked for", () => {
  it("passes a nurse with an email and a facility, and an admin with no facility", () => {
    expect(validateInvite({ email: "a@example.com", role: "staff_nurse", facility: "ph" })).toEqual(
      {},
    );
    expect(validateInvite({ email: "a@example.com", role: "head_nurse", facility: "ph" })).toEqual(
      {},
    );
    expect(validateInvite({ email: "a@example.com", role: "admin", facility: "" })).toEqual({});
  });

  it("asks for an email address that looks like one", () => {
    for (const email of ["", "   ", "nobody", "a@b", "a b@example.com", "@example.com"]) {
      expect(validateInvite({ email, role: "admin", facility: "" }).email).toBe(
        "Enter an email address like name@example.com.",
      );
    }
  });

  it("asks for a facility for a nurse, not for an admin", () => {
    expect(validateInvite({ email: "a@example.com", role: "staff_nurse", facility: "" })).toEqual({
      facility: "Choose the facility this nurse works at.",
    });
    expect(validateInvite({ email: "a@example.com", role: "head_nurse", facility: "" })).toEqual({
      facility: "Choose the facility this nurse works at.",
    });
  });

  it("builds the request with the email trimmed and no facility for an admin", () => {
    expect(
      inviteBody({ email: " New@Example.com ", role: "staff_nurse", facility: "ph" }, "246813"),
    ).toEqual({ email: "New@Example.com", role: "staff_nurse", facility_key: "ph", pin: "246813" });
    expect(
      inviteBody({ email: "b@example.com", role: "admin", facility: "ph" }, "246813").facility_key,
    ).toBeNull();
  });
});

describe("the words of the PIN dialogs", () => {
  const person = { display_name: "Jordan Diaz", email: "jordan.diaz@example.com" };

  it("names the action and the person", () => {
    expect(revokeWords(person).title).toBe("Revoke Jordan Diaz's access?");
    expect(resetWords(person).title).toBe("Reset Jordan Diaz's PIN?");
    expect(resetWords(person).note).toBe(
      "Ask them to sign in and choose a new PIN now, with you there.",
    );
    expect(inviteWords("jordan.diaz@example.com", "head nurse", "Demo Ward").title).toBe(
      "Invite jordan.diaz@example.com?",
    );
  });

  it("says what revoking does and never promises a way back", () => {
    const { question, note } = revokeWords(person);
    expect(`${question} ${note ?? ""}`).toMatch(/signed out/);
    expect(`${question} ${note ?? ""}`).not.toMatch(/again|restore|undo/i);
  });
});
