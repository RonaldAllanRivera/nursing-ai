import { HttpResponse } from "msw";
import type { components } from "../api/schema";

type Schemas = components["schemas"];
export type ProblemCode = Schemas["Problem"]["code"];

const TITLES: Record<number, string> = {
  401: "Not signed in",
  403: "Not allowed",
  404: "Not found",
  422: "The request isn't valid",
  409: "The note can't take this change",
  412: "The note changed",
  423: "Locked",
  428: "A required header is missing",
};

/** An RFC 9457 problem answer, as the server sends it. */
export function problem(
  status: number,
  code: ProblemCode,
  errors?: Schemas["FieldError"][],
  lineIds?: string[],
  triesLeft?: number,
) {
  const body: Schemas["Problem"] = {
    type: "about:blank",
    title: TITLES[status] ?? "Error",
    status,
    code,
    ...(errors ? { errors } : {}),
    ...(lineIds ? { line_ids: lineIds } : {}),
    ...(triesLeft === undefined ? {} : { tries_left: triesLeft }),
  };
  return HttpResponse.json(body, {
    status,
    headers: { "Content-Type": "application/problem+json" },
  });
}

/** A 422 on one field, the way the server words it. */
export function fieldProblem(field: string, message: string) {
  return problem(422, "invalid_request", [{ field, message }]);
}
