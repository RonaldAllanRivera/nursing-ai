import { http, HttpResponse, type HttpHandler } from "msw";
import type { components } from "../api/schema";
import { fieldProblem, problem } from "./problems";
import type { MockSession } from "./session";
import { rowOf, type MockUser } from "./staff";
import type { DemoApi } from "./types";

type Schemas = components["schemas"];

/**
 * The staff list and what can be done to it. A demo persona never lists, invites, revokes or
 * resets anyone: only a Google admin or head nurse can, and every change checks their PIN first.
 */
export function staffRoutes(state: MockSession, data: DemoApi, staff: MockUser[]): HttpHandler[] {
  /** A signed-in, open Google admin or head nurse; everyone else is refused. */
  function actor(request: Request, onlyAdmin: boolean) {
    const gate = state.guard(request);
    if (gate.refusal) return { refusal: gate.refusal };
    const me = state.google();
    const allowed = me && (me.role === "admin" || (!onlyAdmin && me.role === "head_nurse"));
    return allowed ? { me } : { refusal: problem(403, "forbidden") };
  }

  /**
   * The server's order for a change to one person: the person is there and the actor can see them
   * (404 otherwise: an unknown id, and for a head nurse another facility's person), the actor may
   * act on them (403: themselves, and whatever `allowed` adds), and only then the PIN. A refused
   * action counts no wrong try.
   */
  async function target(
    request: Request,
    id: string,
    me: MockUser,
    allowed: (found: MockUser) => boolean,
  ) {
    const found = staff.find((u) => u.id === id);
    const hidden =
      me.role === "head_nurse" &&
      found?.facility_key != null &&
      found.facility_key !== me.facility_key;
    if (!found || hidden) return { refusal: problem(404, "not_found") };
    if (found.id === me.id || !allowed(found)) return { refusal: problem(403, "forbidden") };
    const { pin } = (await request.json()) as Schemas["PinIn"];
    const refusal = state.checkPin(pin);
    return refusal ? { refusal } : { found };
  }

  return [
    http.get("*/api/v1/users", ({ request }) => {
      const checked = actor(request, false);
      if (checked.refusal) return checked.refusal;
      const { me } = checked;
      const rows =
        me.role === "admin" ? staff : staff.filter((u) => u.facility_key === me.facility_key);
      return HttpResponse.json(rows.map(rowOf));
    }),

    http.post("*/api/v1/users", async ({ request }) => {
      const checked = actor(request, true);
      if (checked.refusal) return checked.refusal;
      const body = (await request.json()) as Schemas["InviteIn"];
      const refusal = state.checkPin(body.pin);
      if (refusal) return refusal;
      const email = body.email.trim().toLowerCase();
      if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
        return fieldProblem("body.email", "Enter an email address like name@example.com.");
      }
      const isAdmin = body.role === "admin";
      if (
        isAdmin
          ? body.facility_key !== null
          : !body.facility_key || !data.facilities[body.facility_key]
      ) {
        return fieldProblem(
          "body.facility_key",
          isAdmin ? "An admin belongs to no facility." : "Choose the facility this nurse works at.",
        );
      }
      if (staff.some((u) => u.email.toLowerCase() === email)) return problem(409, "email_taken");
      const added: MockUser = {
        id: `00000000-0000-4000-8000-0000000003${String(staff.length + 1).padStart(2, "0")}`,
        email,
        display_name: email,
        initials: email.charAt(0).toUpperCase(),
        role: body.role,
        facility_key: body.facility_key,
        status: "invited",
        pin_locked: false,
        pin: null,
        failures: 0,
      };
      staff.push(added);
      return HttpResponse.json(rowOf(added), { status: 201 });
    }),

    http.post<{ id: string }>("*/api/v1/users/:id/revoke", async ({ params, request }) => {
      const checked = actor(request, true);
      if (checked.refusal) return checked.refusal;
      const picked = await target(request, params.id, checked.me, () => true);
      if (picked.refusal) return picked.refusal;
      picked.found.status = "revoked";
      return HttpResponse.json(rowOf(picked.found));
    }),

    http.post<{ id: string }>("*/api/v1/users/:id/pin-reset", async ({ params, request }) => {
      const checked = actor(request, false);
      if (checked.refusal) return checked.refusal;
      const { me } = checked;
      // A head nurse resets the staff and head nurses of her own facility, never the admin.
      const picked = await target(
        request,
        params.id,
        me,
        (found) => me.role === "admin" || found.role !== "admin",
      );
      if (picked.refusal) return picked.refusal;
      const { found } = picked;
      // A reset PIN is gone: the person sets a new one at their next sign-in.
      found.pin = null;
      found.failures = 0;
      found.pin_locked = false;
      return HttpResponse.json(rowOf(found));
    }),
  ];
}
