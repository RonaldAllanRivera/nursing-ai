import type { components } from "../api/schema";

type Schemas = components["schemas"];

/** The part of the session the rules read. */
export type StaffActor = Pick<Schemas["SessionOut"], "kind" | "role" | "user_id" | "facility_key">;

/** The part of a staff row the rules read. */
export type StaffTarget = Pick<Schemas["UserOut"], "id" | "role" | "facility_key" | "status">;

/** Only a Google admin or head nurse has this screen; a demo persona never does (the API answers 403). */
export function canSeeStaff(actor: StaffActor): boolean {
  return actor.kind === "google" && (actor.role === "admin" || actor.role === "head_nurse");
}

/** The admin alone invites. */
export function canInvite(actor: StaffActor): boolean {
  return actor.kind === "google" && actor.role === "admin";
}

/** The admin ends anyone's access but their own; a revoked row has nothing left to end. */
export function canRevoke(actor: StaffActor, target: StaffTarget): boolean {
  return canInvite(actor) && target.id !== actor.user_id && target.status !== "revoked";
}

/**
 * Whether the actor may clear this person's PIN (locked or not, the server allows both). The admin
 * resets anyone but themselves; a head nurse a staff or head nurse of her facility, never herself.
 * A person who has not signed in yet has no PIN to reset, and a revoked person cannot sign in.
 */
export function canResetPin(actor: StaffActor, target: StaffTarget): boolean {
  if (!canSeeStaff(actor) || target.id === actor.user_id) return false;
  if (target.status !== "active") return false;
  if (actor.role === "admin") return true;
  return target.role !== "admin" && target.facility_key === actor.facility_key;
}

const RANK = { active: 1, invited: 2, revoked: 3 } as const;

/** A locked PIN needs someone to act, so it comes first; then active, invited and revoked people, each by name. */
export function sortStaff<T extends StaffTarget & { display_name: string; pin_locked: boolean }>(
  rows: readonly T[],
): T[] {
  const rank = (row: T) => (row.status === "active" && row.pin_locked ? 0 : RANK[row.status]);
  return [...rows].sort(
    (a, b) => rank(a) - rank(b) || a.display_name.localeCompare(b.display_name),
  );
}
