import { describe, expect, it } from "vitest";
import type { Problem } from "../api/errors";
import { gateFromProblem } from "./gate";

const problem = (status: number, code: Problem["code"]): Problem => ({
  status,
  code,
  title: "x",
  type: "about:blank",
});

describe("gateFromProblem", () => {
  it.each(["set_pin", "enter_pin", "idle_locked", "pin_locked"] as const)(
    "a 423 problem names the gate: %s",
    (code) => {
      expect(gateFromProblem(problem(423, code))).toBe(code);
    },
  );

  it.each([
    ["a 423 with another code", problem(423, "forbidden")],
    ["a 403", problem(403, "csrf_failed")],
    ["a 401", problem(401, "not_signed_in")],
    ["a non-423 with a gate code", problem(403, "enter_pin")],
    ["no problem", undefined],
  ])("is null for %s", (_name, p) => {
    expect(gateFromProblem(p)).toBeNull();
  });
});
