import { http, HttpResponse, type HttpHandler } from "msw";
import type { components } from "../api/schema";
import type { MockOptions } from "./options";
import { DEMO_PIN, isPinFormat, isWeakPin, PIN_FORMAT_MESSAGE, PIN_WEAK_MESSAGE } from "./pin";
import { fieldProblem, problem } from "./problems";
import type { MockSession } from "./session";

type Schemas = components["schemas"];

/** The sign-in page's options, and the two routes that set and enter a PIN (they answer at any gate). */
export function sessionRoutes(state: MockSession, options: MockOptions): HttpHandler[] {
  const demo = options.demo ?? true;

  return [
    http.get("*/api/v1/sign-in-options", () => {
      const body: Schemas["SignInOptionsOut"] = {
        google: options.google ?? false,
        personas: true,
        demo,
        demo_pin: demo ? DEMO_PIN : null,
      };
      return HttpResponse.json(body);
    }),

    http.post("*/api/v1/session/pin", async ({ request }) => {
      const checked = state.guardSession(request);
      if (checked.refusal) return checked.refusal;
      const { pin } = (await request.json()) as Schemas["PinIn"];
      if (!isPinFormat(pin)) return fieldProblem("body.pin", PIN_FORMAT_MESSAGE);
      const google = state.google();
      if (checked.session.gate !== "set_pin" || !google) return problem(409, "pin_already_set");
      // Nothing marks a session active before its PIN is set, so this is the time since the
      // Google sign-in. Past the idle lock she may have walked away: the session ends (the server's rule).
      if (state.idleSinceActive()) {
        state.end();
        return problem(401, "not_signed_in");
      }
      if (isWeakPin(pin)) return fieldProblem("body.pin", PIN_WEAK_MESSAGE);
      google.pin = pin;
      google.failures = 0;
      state.setGate("open");
      return HttpResponse.json(state.session());
    }),

    http.post("*/api/v1/session/unlock", async ({ request }) => {
      const checked = state.guardSession(request);
      if (checked.refusal) return checked.refusal;
      const { gate } = checked.session;
      // As the server: the two gates a PIN can't open answer 423 with the gate; any other gate,
      // open included, checks the PIN (a wrong one counts).
      if (gate === "pin_locked" || gate === "set_pin") return problem(423, gate);
      const { pin } = (await request.json()) as Schemas["PinIn"];
      const refusal = state.checkPin(pin);
      if (refusal) return refusal;
      state.setGate("open");
      return HttpResponse.json(state.session());
    }),
  ];
}
