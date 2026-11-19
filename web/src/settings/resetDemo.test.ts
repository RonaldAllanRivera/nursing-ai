import { describe, expect, it } from "vitest";
import type { Session } from "../session/session";
import type { SignInOptions } from "../session/signInOptions";
import { canResetDemo } from "./resetDemo";

const session = (kind: Session["kind"], role: Session["role"]) => ({ kind, role }) as Session;
const options = (demo: boolean) => ({ demo }) as SignInOptions;

describe("canResetDemo", () => {
  it("is for the demo's admin persona while the demo is on", () => {
    expect(canResetDemo(session("persona", "admin"), options(true))).toBe(true);
  });

  it("is not for a Google admin, another role, or a demo that is off", () => {
    expect(canResetDemo(session("google", "admin"), options(true))).toBe(false);
    expect(canResetDemo(session("persona", "head_nurse"), options(true))).toBe(false);
    expect(canResetDemo(session("persona", "admin"), options(false))).toBe(false);
  });

  it("waits for the options and the session before it shows", () => {
    expect(canResetDemo(session("persona", "admin"), undefined)).toBe(false);
    expect(canResetDemo(undefined, options(true))).toBe(false);
    expect(canResetDemo(null, options(true))).toBe(false);
  });
});
