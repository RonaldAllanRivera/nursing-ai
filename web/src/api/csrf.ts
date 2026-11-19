import type { Session } from "../session/session";

const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);

/** The header every signed-in change must carry, or `{}` for a read or when nobody is signed in. */
export function csrfHeaders(
  method: string,
  session: Pick<Session, "csrf_token"> | null | undefined,
): Record<string, string> {
  if (!session || !UNSAFE.has(method.toUpperCase())) return {};
  return { "X-CSRF-Token": session.csrf_token };
}
