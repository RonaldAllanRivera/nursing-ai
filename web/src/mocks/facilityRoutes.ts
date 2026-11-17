import { http, HttpResponse, type HttpHandler } from "msw";
import type { components } from "../api/schema";
import type { FacilitySettings } from "../api/client";
import type { MockOptions } from "./options";
import { problem } from "./problems";
import type { MockSession } from "./session";
import type { DemoApi } from "./types";

type Schemas = components["schemas"];

// The server's rules for a facility's settings (core's `FacilitySettings`), copied here and not
// imported from the screen, so a disagreement between the screen and the server shows in a test.

type Settings = FacilitySettings;

/** The settings in a save, without the PIN that proves who saved: the PIN is never stored. */
function settingsOf(sent: Schemas["FacilityUpdateIn"]): Settings {
  const settings: Partial<Schemas["FacilityUpdateIn"]> = { ...sent };
  delete settings.pin;
  return settings as Settings;
}

/** "HH:MM" or "HH:MM:00" as minutes since midnight, or null (not a whole-minute local time). */
function localMinutes(value: unknown): number | null {
  const found = typeof value === "string" ? /^(\d{2}):(\d{2})(?::00)?$/.exec(value) : null;
  if (!found) return null;
  const hours = Number(found[1]);
  const minutes = Number(found[2]);
  return hours < 24 && minutes < 60 ? hours * 60 + minutes : null;
}

function wholeTime(minutes: number): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(Math.floor(minutes / 60))}:${pad(minutes % 60)}:00`;
}

function isIanaZone(value: unknown): boolean {
  if (typeof value !== "string" || value === "") return false;
  try {
    new Intl.DateTimeFormat("en", { timeZone: value });
    return true;
  } catch {
    return false;
  }
}

function textBetween(value: unknown, max: number): boolean {
  return typeof value === "string" && value.trim().length >= 1 && value.trim().length <= max;
}

/** The field-level checks first; the whole-table checks only when those pass (as pydantic does). */
function settingsErrors(body: Settings): Schemas["FieldError"][] {
  const errors: Schemas["FieldError"][] = [];
  const add = (field: string, message: string) => errors.push({ field, message });
  if (!textBetween(body.name, 120)) add("body.name", "A name is 1 to 120 characters.");
  if (!isIanaZone(body.timezone)) {
    add("body.timezone", "Timezone must be an IANA zone such as Europe/Paris.");
  }
  // The body is untrusted JSON: the types say what it should be, not what it is.
  if (!["en-PH", "en-US"].includes(body.locale)) {
    add("body.locale", "Choose a locale from the list.");
  }
  if (!["24h", "12h"].includes(body.clock)) {
    add("body.clock", "Choose 24-hour or 12-hour.");
  }
  if (localMinutes(body.day_starts_at) === null) {
    add("body.day_starts_at", "A time in whole minutes, like 06:00.");
  }
  if (!Array.isArray(body.shifts) || body.shifts.length < 1) {
    add("body.shifts", "Add at least one shift.");
  } else {
    body.shifts.forEach((shift, i) => {
      if (!textBetween(shift.code, 16))
        add(`body.shifts.${String(i)}.code`, "A code is 1 to 16 characters.");
      if (!textBetween(shift.label, 40))
        add(`body.shifts.${String(i)}.label`, "A label is 1 to 40 characters.");
      if (localMinutes(shift.starts_local) === null) {
        add(`body.shifts.${String(i)}.starts_local`, "A time in whole minutes, like 06:00.");
      }
      if (localMinutes(shift.ends_local) === null) {
        add(`body.shifts.${String(i)}.ends_local`, "A time in whole minutes, like 06:00.");
      }
      if (!["blue", "black", "red"].includes(shift.ink)) {
        add(`body.shifts.${String(i)}.ink`, "Choose blue, black or red.");
      }
      if (
        localMinutes(shift.starts_local) !== null &&
        localMinutes(shift.starts_local) === localMinutes(shift.ends_local)
      ) {
        add(`body.shifts.${String(i)}`, "A shift must end at a different time than it starts.");
      }
    });
  }
  if (errors.length > 0) return errors;

  const whole = (message: string) => [{ field: "body", message }];
  const codes = body.shifts.map((s) => s.code.trim());
  if (new Set(codes).size !== codes.length) return whole("Shift codes must be unique.");
  const shifts = body.shifts
    .map((s) => ({
      start: localMinutes(s.starts_local) ?? 0,
      end: localMinutes(s.ends_local) ?? 0,
    }))
    .sort((a, b) => a.start - b.start);
  for (const [i, current] of shifts.entries()) {
    const following = shifts[(i + 1) % shifts.length];
    if (current.end !== following?.start) {
      return whole("Shifts must cover 24 hours with no gap or overlap.");
    }
  }
  if (!shifts.some((s) => s.start === localMinutes(body.day_starts_at))) {
    return whole("The day must start when one of the shifts starts.");
  }
  return [];
}

/** The facilities: read, save the settings (with the PIN), and put the demo's settings back. */
export function facilityRoutes(
  state: MockSession,
  data: DemoApi,
  source: DemoApi,
  options: MockOptions,
): HttpHandler[] {
  const { guard } = state;
  return [
    http.get("*/api/v1/facilities", ({ request }) => {
      const gated = guard(request);
      if (gated.refusal) return gated.refusal;
      const current = gated.session;
      const all = Object.values(data.facilities);
      const key = current.facility_key;
      return HttpResponse.json(key === null ? all : all.filter((f) => f.profile.key === key));
    }),

    http.get<{ key: string }>("*/api/v1/facilities/:key", ({ params, request }) => {
      const gated = guard(request);
      if (gated.refusal) return gated.refusal;
      const current = gated.session;
      const found = data.facilities[params.key];
      if (!found) return problem(404, "not_found");
      if (current.facility_key !== null && current.facility_key !== params.key) {
        return problem(403, "forbidden");
      }
      return HttpResponse.json(found, { headers: { ETag: `"f${String(found.version)}"` } });
    }),

    http.put<{ key: string }>("*/api/v1/facilities/:key", async ({ params, request }) => {
      const gated = guard(request);
      if (gated.refusal) return gated.refusal;
      const current = gated.session;
      if (current.facility_key !== null) return problem(403, "forbidden");
      const found = data.facilities[params.key];
      if (!found) return problem(404, "not_found");
      const ifMatch = request.headers.get("If-Match");
      if (!ifMatch) return problem(428, "precondition_required");
      if (ifMatch !== `"f${String(found.version)}"`) return problem(412, "stale_version");
      const sentBody = (await request.json()) as Schemas["FacilityUpdateIn"];
      const wrongPin = state.checkPin(sentBody.pin);
      if (wrongPin) return wrongPin;
      const body = settingsOf(sentBody);
      const errors = settingsErrors(body);
      if (errors.length > 0) return problem(422, "invalid_request", errors);
      const shifts = body.shifts.map((s) => ({
        code: s.code.trim(),
        label: s.label.trim(),
        starts_local: wholeTime(localMinutes(s.starts_local) ?? 0),
        ends_local: wholeTime(localMinutes(s.ends_local) ?? 0),
        ink: s.ink,
      }));
      found.profile = {
        ...body,
        key: params.key,
        name: body.name.trim(),
        day_starts_at: wholeTime(localMinutes(body.day_starts_at) ?? 0),
        shifts,
      };
      found.version += 1;
      // The demo's shift choices are fixed dates; a rename shows in them, and a removed code goes.
      found.shift_choices = found.shift_choices.flatMap((choice) => {
        const kept = shifts.find((s) => s.code === choice.code);
        return kept ? [{ ...choice, label: kept.label }] : [];
      });
      return HttpResponse.json(found, { headers: { ETag: `"f${String(found.version)}"` } });
    }),

    http.post<{ key: string }>("*/api/v1/facilities/:key/reset", async ({ params, request }) => {
      const gated = guard(request);
      if (gated.refusal) return gated.refusal;
      const { kind, role } = gated.session;
      if (!(options.demo ?? true) || kind !== "persona" || role !== "admin") {
        return problem(403, "forbidden");
      }
      const found = data.facilities[params.key];
      const demoCopy = source.facilities[params.key];
      if (!found || !demoCopy) return problem(404, "not_found");
      const ifMatch = request.headers.get("If-Match");
      if (!ifMatch) return problem(428, "precondition_required");
      if (ifMatch !== `"f${String(found.version)}"`) return problem(412, "stale_version");
      const wrongPin = state.checkPin(((await request.json()) as Schemas["PinIn"]).pin);
      if (wrongPin) return wrongPin;
      found.profile = structuredClone(demoCopy.profile);
      found.shift_choices = structuredClone(demoCopy.shift_choices);
      found.version += 1;
      return HttpResponse.json(found, { headers: { ETag: `"f${String(found.version)}"` } });
    }),
  ];
}
