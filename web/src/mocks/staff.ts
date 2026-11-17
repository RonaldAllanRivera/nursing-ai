import type { components } from "../api/schema";

type Schemas = components["schemas"];

/**
 * The PIN of every mock Google user (the demo personas use the demo PIN). It passes the PIN rules
 * and is not the demo PIN, so a test can tell which kind of user it signed in as.
 */
export const MOCK_PIN = "246813";

/** A staff member the mock keeps: the row the API shows, plus what the server keeps private. */
export type MockUser = Schemas["UserOut"] & {
  /** `null` until they set one (a new person, or after a PIN reset). */
  pin: string | null;
  /** Wrong tries since the last right one; the fifth locks the PIN. */
  failures: number;
};

/** The addresses of the mock staff, for tests and Playwright (`account: { user: ... }`). */
export const MOCK_EMAILS = {
  admin: "dana.admin@example.com",
  phHead: "hana.reyes@example.com",
  phStaff: "paolo.cruz@example.com",
  phInvited: "irene.lim@example.com",
  phLocked: "lito.santos@example.com",
  usHead: "holly.grant@example.com",
  usStaff: "sam.porter@example.com",
  usRevoked: "rita.moore@example.com",
} as const;

function user(
  n: number,
  email: string,
  name: string,
  role: Schemas["Role"],
  facility: string | null,
  status: Schemas["UserStatus"] = "active",
  locked = false,
): MockUser {
  const initials = name
    .split(" ")
    .map((word) => word.charAt(0))
    .join("");
  return {
    id: `00000000-0000-4000-8000-0000000003${String(n).padStart(2, "0")}`,
    email,
    display_name: name,
    initials,
    role,
    facility_key: facility,
    status,
    pin_locked: locked,
    pin: status === "invited" ? null : MOCK_PIN,
    failures: locked ? 5 : 0,
  };
}

/** A fresh copy each time, because every mock starts clean. Synthetic names, example.com only. */
export function createStaff(): MockUser[] {
  const e = MOCK_EMAILS;
  return [
    user(1, e.admin, "Dana Admin", "admin", null),
    user(2, e.phHead, "Hana Reyes", "head_nurse", "ph-demo"),
    user(3, e.phStaff, "Paolo Cruz", "staff_nurse", "ph-demo"),
    user(4, e.phInvited, "Irene Lim", "staff_nurse", "ph-demo", "invited"),
    user(5, e.phLocked, "Lito Santos", "staff_nurse", "ph-demo", "active", true),
    user(6, e.usHead, "Holly Grant", "head_nurse", "us-demo"),
    user(7, e.usStaff, "Sam Porter", "staff_nurse", "us-demo"),
    user(8, e.usRevoked, "Rita Moore", "staff_nurse", "us-demo", "revoked"),
  ];
}

/** The row as the API shows it: no PIN, no counter. */
export function rowOf(found: MockUser): Schemas["UserOut"] {
  return {
    id: found.id,
    email: found.email,
    display_name: found.display_name,
    initials: found.initials,
    role: found.role,
    facility_key: found.facility_key,
    status: found.status,
    pin_locked: found.pin_locked,
  };
}
