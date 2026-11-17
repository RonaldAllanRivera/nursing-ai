import { http, HttpResponse, type HttpHandler } from "msw";
import type { components } from "../api/schema";
import type { MockOptions } from "./options";
import { DEMO_PIN, isPinFormat, isWeakPin, PIN_FORMAT_MESSAGE, PIN_WEAK_MESSAGE } from "./pin";
import { fieldProblem, problem } from "./problems";
import type { MockSession } from "./session";

type Schemas = components["schemas"];

/** The sign-in page's options, and the two routes that set and enter a PIN (they work at any gate). */
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
      if (gate === "pin_locked") return problem(423, "pin_locked");
      if (gate !== "enter_pin" && gate !== "idle_locked") return problem(409, "invalid_request");
      const { pin } = (await request.json()) as Schemas["PinIn"];
      const refusal = state.checkPin(pin);
      if (refusal) return refusal;
      state.setGate("open");
      return HttpResponse.json(state.session());
    }),
  ];
}
