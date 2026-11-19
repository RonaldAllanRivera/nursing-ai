import type { Session } from "../session/session";
import type { SignInOptions } from "../session/signInOptions";

export const RESET_TITLE = "Reset demo settings";
export const RESET_QUESTION = "Put this facility's settings back to how the demo started?";
export const RESET_DROPS = "Changes you haven't saved are dropped.";
export const RESET_DONE = "Settings are back to how the demo started.";

/**
 * Whether to show "Reset demo settings": only the demo's admin persona, and only while the demo is
 * on. A Google admin never sees it (the server refuses them too).
 */
export function canResetDemo(
  session: Session | null | undefined,
  options: SignInOptions | undefined,
): boolean {
  return session?.kind === "persona" && session.role === "admin" && options?.demo === true;
}
