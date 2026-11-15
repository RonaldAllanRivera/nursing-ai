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

/** Turns an openapi-fetch answer into its data, or throws an `ApiError` for TanStack Query. */
export function unwrap<D>(answer: Answer<D>): D {
  if (answer.response.ok && answer.data !== undefined) return answer.data;
  const error = answer.error;
  const problem =
    typeof error === "object" && error !== null && "code" in error ? (error as Problem) : undefined;
  throw new ApiError(answer.response.status, problem);
}

/** For answers with no body (204). */
export function ensureOk(answer: Answer<unknown>): void {
  if (answer.response.ok) return;
  const error = answer.error;
  const problem =
    typeof error === "object" && error !== null && "code" in error ? (error as Problem) : undefined;
  throw new ApiError(answer.response.status, problem);
}
