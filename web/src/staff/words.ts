interface Person {
  display_name: string;
}

/** The words a PIN dialog shows (`PinDialog`'s `words`). */
export interface DialogWords {
  title: string;
  question: string;
  note?: string | null;
  confirm: string;
  busy: string;
}

export function revokeWords(person: Person): DialogWords {
  return {
    title: `Revoke ${person.display_name}'s access?`,
    question: "They are signed out at once and can't sign in. Notes they signed stay as they are.",
    note: "Enter your PIN to confirm.",
    confirm: "Revoke access",
    busy: "Revoking…",
  };
}

export function resetWords(person: Person): DialogWords {
  return {
    title: `Reset ${person.display_name}'s PIN?`,
    question: "Enter your PIN to confirm.",
    note: "They will choose a new one at their next sign-in.",
    confirm: "Reset PIN",
    busy: "Resetting…",
  };
}

export function inviteWords(email: string, role: string, facility: string | null): DialogWords {
  return {
    title: `Invite ${email}?`,
    question: `They can sign in with Google as ${role === "admin" ? "an" : "a"} ${role}${facility ? ` at ${facility}` : ""}. Enter your PIN to confirm.`,
    confirm: "Send invite",
    busy: "Inviting…",
  };
}

/** What the page says after an action worked (a status line, read aloud). */
export const DONE = {
  revoked: (person: Person) => `${person.display_name}'s access is revoked.`,
  reset: (person: Person) =>
    `${person.display_name}'s PIN is reset. They will choose a new one at their next sign-in.`,
  invited: (email: string) => `${email} is invited. They can now sign in with Google.`,
};
