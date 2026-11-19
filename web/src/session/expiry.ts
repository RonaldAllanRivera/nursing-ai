import type { QueryClient } from "@tanstack/react-query";
import { facilityQuery } from "../facility/useFacility";
import type { Session } from "./session";

/** The admin has no facility, and works on the default 12 hours. */
const DEFAULT_HOURS = 12;

/** What the sign-in screen says after a session reached its hard limit. */
export function sessionEndedWords(hours: number): string {
  return `Your session ended after ${String(hours)} ${hours === 1 ? "hour" : "hours"}. Sign in again.`;
}

/** Whether `expiresAt` (an ISO instant) has come. Anything that is not a date has not. */
export function isPastExpiry(expiresAt: string, now: number): boolean {
  const at = Date.parse(expiresAt);
  return !Number.isNaN(at) && now >= at;
}

/** The facility's session hours from what is already loaded (the header keeps it loaded). */
export function sessionHours(queryClient: QueryClient, session: Session): number {
  if (session.facility_key === null) return DEFAULT_HOURS;
  const facility = queryClient.getQueryData(facilityQuery(session.facility_key).queryKey);
  return facility?.profile.session_max_hours ?? DEFAULT_HOURS;
}
