import type { components } from "../api/schema";

export type SignInOptions = components["schemas"]["SignInOptionsOut"];

/** The Google link is a full-page navigation: the server starts the sign-in and sends her back. */
export const GOOGLE_START = "/api/v1/auth/google/start";

/** On every screen while the demo is on. A standing caution, not an alarm. */
export const DEMO_BANNER = "Synthetic patients only. Never type real patient details.";

/** The only reasons the server sends a refused Google sign-in back with (`?error=`). */
export const SIGN_IN_ERRORS = ["no_access", "expired", "cancelled"] as const;
export type SignInError = (typeof SIGN_IN_ERRORS)[number];

export const SIGN_IN_MESSAGES: Record<SignInError, string> = {
  no_access: "You don't have access yet. Ask the admin to invite your Google account.",
  expired: "That sign-in took too long or was started in another tab. Sign in with Google again.",
  cancelled: "Google sign-in was cancelled. Sign in again when you're ready.",
};

/** The `error` in the address, if it is one of the three; any other value counts as absent. */
export function signInErrorFrom(search: Record<string, unknown>): SignInError | undefined {
  const error = search["error"];
  return SIGN_IN_ERRORS.find((known) => known === error);
}

export interface Offered {
  google: boolean;
  personas: boolean;
  demoPin: string | null;
  banner: boolean;
}

/** When the options can't be had: the persona list alone, nothing that needs the options. */
export const SIGN_IN_FALLBACK: Offered = {
  google: false,
  personas: true,
  demoPin: null,
  banner: false,
};

/** What the sign-in screen (and the banner) offers, given the server's answer (or none). */
export function offeredFrom(options: SignInOptions | undefined): Offered {
  if (!options) return SIGN_IN_FALLBACK;
  return {
    google: options.google,
    personas: options.personas,
    demoPin: options.personas ? options.demo_pin : null,
    banner: options.demo,
  };
}
