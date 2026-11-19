import type { components } from "./schema";

export type Problem = components["schemas"]["Problem"];

/** A non-2xx answer. `status` is the HTTP status (a 401 means the session is gone). */
export class ApiError extends Error {
  status: number;
  problem: Problem | undefined;

  constructor(status: number, problem?: Problem) {
    super(problem?.title ?? `The request failed (${String(status)}).`);
    this.name = "ApiError";
    this.status = status;
    this.problem = problem;
  }
}

interface Answer<D> {
  data?: D | undefined;
  error?: unknown;
  response: Response;
}

function toApiError(answer: Answer<unknown>): ApiError {
  const error = answer.error;
  const problem =
    typeof error === "object" && error !== null && "code" in error ? (error as Problem) : undefined;
  return new ApiError(answer.response.status, problem);
}

/**
 * The client's own refusal to send a request a second time: the first try was caught by the
 * session's new cookie (answered 401 although she is signed in) and the request carries a PIN, or
 * the session turned out to be someone else's. Nothing was read or counted by the server.
 */
export class SignInRefreshedError extends Error {
  constructor() {
    super("The sign-in was refreshed, so the request was not sent again.");
    this.name = "SignInRefreshedError";
  }
}

/**
 * A change refused because the CSRF token it carried was out of date (a 403 `csrf_failed`).
 * Nothing was done, and nobody is to blame: the session is fetched again (the query client does
 * it), which brings a fresh token, so the person can simply try again.
 */
export function isCsrfFailure(error: unknown): boolean {
  return error instanceof ApiError && error.status === 403 && error.problem?.code === "csrf_failed";
}

/** Turns an openapi-fetch answer into its data, or throws an `ApiError` for TanStack Query. */
export function unwrap<D>(answer: Answer<D>): D {
  if (answer.response.ok && answer.data !== undefined) return answer.data;
  throw toApiError(answer);
}

/** For answers with no body (204). */
export function ensureOk(answer: Answer<unknown>): void {
  if (answer.response.ok) return;
  throw toApiError(answer);
}
