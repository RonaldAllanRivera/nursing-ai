import { z } from "zod";
import type { components } from "../api/schema";

type Schemas = components["schemas"];

/** What the form holds. Times are "HH:MM", the 24-hour form a time input uses. */
export interface FormValues {
  name: string;
  timezone: string;
  locale: "en-PH" | "en-US";
  day_starts_at: string;
  shifts: {
    code: string;
    label: string;
    starts_local: string;
    ends_local: string;
    ink: "blue" | "black" | "red";
  }[];
  temperature: "Cel" | "[degF]";
  weight: "kg" | "[lb_av]" | "none";
  clock: "24h" | "12h";
}

/** The zones the timezone box offers, and the only ones it accepts. */
export function timeZones(): string[] {
  return Intl.supportedValuesOf("timeZone");
}

/** The field-level rules (what the server checks on each field). The whole-table rules are `checkShifts`. */
export function settingsSchema(zones: readonly string[] = timeZones()) {
  const known = new Set(zones);
  const time = (message: string) => z.string().regex(/^\d{2}:\d{2}$/, message);
  return z.object({
    name: z
      .string()
      .trim()
      .min(1, "Enter the facility's name.")
      .max(120, "Use 120 characters or fewer."),
    timezone: z
      .string()
      .trim()
      .refine(
        (value) => known.has(value),
        "Choose a timezone from the list, such as Europe/Paris.",
      ),
    locale: z.enum(["en-PH", "en-US"], "Choose a locale."),
    day_starts_at: time("Enter the time the nursing day starts."),
    shifts: z.array(
      z.object({
        code: z.string().trim().min(1, "Enter a code.").max(16, "Use 16 characters or fewer."),
        label: z.string().trim().min(1, "Enter a label.").max(40, "Use 40 characters or fewer."),
        starts_local: time("Enter the time the shift starts."),
        ends_local: time("Enter the time the shift ends."),
        ink: z.enum(["blue", "black", "red"], "Choose an ink."),
      }),
    ),
    temperature: z.enum(["Cel", "[degF]"], "Choose a temperature unit."),
    weight: z.enum(["kg", "[lb_av]", "none"], "Choose a weight unit."),
    clock: z.enum(["24h", "12h"], "Choose 24-hour or 12-hour."),
  });
}

const hhmm = (time: string) => time.slice(0, 5);

/** The server's settings as the form's values. */
export function toFormValues(facility: Schemas["FacilityOut"]): FormValues {
  const p = facility.profile;
  return {
    name: p.name,
    timezone: p.timezone,
    locale: p.locale,
    day_starts_at: hhmm(p.day_starts_at),
    shifts: p.shifts.map((s) => ({
      code: s.code,
      label: s.label,
      starts_local: hhmm(s.starts_local),
      ends_local: hhmm(s.ends_local),
      ink: s.ink,
    })),
    temperature: p.units.temperature === "[degF]" ? "[degF]" : "Cel",
    weight: p.units.weight === "[lb_av]" ? "[lb_av]" : p.units.weight === null ? "none" : "kg",
    clock: p.clock,
  };
}

/** The form's values as the body of the PUT. FDAR is the only format built so far. */
export function toSettings(values: FormValues): Schemas["FacilitySettings"] {
  return {
    name: values.name.trim(),
    timezone: values.timezone.trim(),
    locale: values.locale,
    day_starts_at: `${values.day_starts_at}:00`,
    shifts: values.shifts.map((s) => ({
      code: s.code.trim(),
      label: s.label.trim(),
      starts_local: `${s.starts_local}:00`,
      ends_local: `${s.ends_local}:00`,
      ink: s.ink,
    })),
    note_formats: ["fdar"],
    default_note_format: "fdar",
    units: {
      temperature: values.temperature,
      weight: values.weight === "none" ? null : values.weight,
      volume: "mL",
    },
    clock: values.clock,
  };
}

export interface MappedProblems {
  /** Errors that belong to one field, by the form's own field name. */
  fields: { name: string; message: string }[];
  /** Errors on the whole body (or the shifts list): they show above the shifts table. */
  table: string[];
  /** Errors that match no field on the screen. */
  other: string[];
}

const SHIFT_PART = /^shifts\.(\d+)\.(code|label|starts_local|ends_local|ink)$/;

/**
 * The server's `errors[].field` ("body.shifts.1.label") as the form's field name ("shifts.1.label").
 * `body` itself, and the shifts list as a whole, belong above the shifts table.
 */
export function mapProblems(errors: readonly Schemas["FieldError"][]): MappedProblems {
  const mapped: MappedProblems = { fields: [], table: [], other: [] };
  for (const { field, message } of errors) {
    const path = field === "body" ? "" : field.replace(/^body\./, "");
    const alias: Record<string, string> = {
      "units.temperature": "temperature",
      "units.weight": "weight",
    };
    const name = alias[path] ?? path;
    const zeroLength = /^shifts\.(\d+)$/.exec(name);
    if (name === "" || name === "shifts") {
      mapped.table.push(message);
    } else if (zeroLength) {
      mapped.fields.push({ name: `shifts.${zeroLength[1] ?? "0"}.ends_local`, message });
    } else if (
      ["name", "timezone", "locale", "day_starts_at", "clock", "temperature", "weight"].includes(
        name,
      ) ||
      SHIFT_PART.test(name)
    ) {
      mapped.fields.push({ name, message });
    } else {
      mapped.other.push(message);
    }
  }
  return mapped;
}
