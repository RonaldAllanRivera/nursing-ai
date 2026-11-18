import type { components } from "../api/schema";

type Schemas = components["schemas"];

/** What the invite form holds. `facility` is "" until one is chosen. */
export interface InviteValues {
  email: string;
  role: Schemas["Role"];
  facility: string;
}

export interface InviteProblems {
  email?: string;
  facility?: string;
}

export const EMAIL_PROBLEM = "Enter an email address like name@example.com.";
export const FACILITY_PROBLEM = "Choose the facility this nurse works at.";
export const EMAIL_TAKEN = "That email is already on the list.";

/** What is wrong with the form, field by field, so nothing is sent (and no PIN asked for) until it is right. */
export function validateInvite(values: InviteValues): InviteProblems {
  const problems: InviteProblems = {};
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(values.email.trim())) problems.email = EMAIL_PROBLEM;
  if (values.role !== "admin" && values.facility === "") problems.facility = FACILITY_PROBLEM;
  return problems;
}

/** The request: an admin belongs to no facility, whatever the facility picker last held. */
export function inviteBody(values: InviteValues, pin: string): Schemas["InviteIn"] {
  return {
    email: values.email.trim(),
    role: values.role,
    facility_key: values.role === "admin" ? null : values.facility,
    pin,
  };
}
