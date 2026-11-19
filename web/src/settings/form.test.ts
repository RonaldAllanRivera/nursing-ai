import { describe, expect, it } from "vitest";
import { demoApi } from "../mocks/demo-api";
import {
  isUsableTimeZone,
  mapProblems,
  resetFailureText,
  saveFailureText,
  settingsSchema,
  timeZoneSuggestions,
  toFormValues,
  toSettings,
} from "./form";

const ph = demoApi.facilities["ph-demo"];
const us = demoApi.facilities["us-demo"];

describe("settings form values", () => {
  it("round-trips both demo facilities", () => {
    for (const facility of [ph, us]) {
      if (!facility) throw new Error("no demo facility");
      const { key, ...settings } = facility.profile;
      expect(key).toBe(facility.profile.key);
      expect(toSettings(toFormValues(facility))).toEqual(settings);
    }
  });

  it("keeps the facility's session length through the form's rules", () => {
    // No field shows it yet, but a save must never put a 14-hour facility back to 12.
    if (!us) throw new Error("no demo facility");
    const parsed = settingsSchema().parse(toFormValues(us));
    expect(toSettings(parsed).session_max_hours).toBe(14);
  });

  it("accepts both demo facilities' values", () => {
    for (const facility of [ph, us]) {
      if (!facility) throw new Error("no demo facility");
      expect(settingsSchema().safeParse(toFormValues(facility)).success).toBe(true);
    }
  });

  it("says no to a timezone nobody knows, an empty name and a long label", () => {
    if (!ph) throw new Error("no demo facility");
    const values = toFormValues(ph);
    const result = settingsSchema().safeParse({
      ...values,
      name: "  ",
      timezone: "Mars/Base",
      shifts: [{ ...(values.shifts[0] ?? {}), label: "x".repeat(41) }],
    });
    expect(result.success).toBe(false);
    const paths = result.error?.issues.map((i) => i.path.join(".")) ?? [];
    expect(paths).toEqual(["name", "timezone", "shifts.0.label"]);
  });
});

describe("isUsableTimeZone", () => {
  it("takes every zone the browser can use, including ones its own list leaves out", () => {
    for (const zone of ["Europe/Paris", "UTC", "Etc/UTC", "Asia/Kolkata", "America/New_York"]) {
      expect(isUsableTimeZone(zone)).toBe(true);
    }
  });

  it("turns away nonsense and an empty box", () => {
    for (const zone of ["Mars/Base", "", "   ", "Not a zone"]) {
      expect(isUsableTimeZone(zone)).toBe(false);
    }
  });
});

describe("timeZoneSuggestions", () => {
  it("adds the facility's own zone and UTC to the browser's list, once each", () => {
    const list = timeZoneSuggestions("Atlantis/Lost");
    expect(list).toContain("Atlantis/Lost");
    expect(list).toContain("UTC");
    expect(list).toContain("Europe/Paris");
    expect(new Set(list).size).toBe(list.length);
    expect(timeZoneSuggestions("Europe/Paris").filter((z) => z === "Europe/Paris")).toHaveLength(1);
  });
});

describe("resetFailureText", () => {
  it("says what happened for each way the reset can be refused", () => {
    expect(resetFailureText(null)).toContain("connection");
    expect(resetFailureText(403)).toContain("demo's admin");
    expect(resetFailureText(404)).toContain("no longer there");
    expect(resetFailureText(500)).toContain("try again");
  });

  it("says a change refused for a stale token was not made, and to try again", () => {
    expect(resetFailureText(403, "csrf_failed")).toBe("The settings were not put back. Try again.");
  });

  it("does not blame an out-of-date page for a 422 or a status it does not know", () => {
    for (const status of [422, 409, 423, 418]) {
      const text = resetFailureText(status);
      expect(text).not.toContain("out of date");
      expect(text).toContain("did not accept");
    }
  });
});

describe("saveFailureText", () => {
  it("gives a next step that fits the failure", () => {
    expect(saveFailureText(null)).toContain("connection");
    expect(saveFailureText(403)).toContain("sign in as the admin");
    expect(saveFailureText(404)).toContain("Reload the page");
    expect(saveFailureText(428)).toContain("out of date");
    expect(saveFailureText(500)).toContain("try again");
    expect(saveFailureText(422)).toContain("named no field");
  });

  it("says a save refused for a stale token was not made, and to try again, not to sign in again", () => {
    expect(saveFailureText(403, "csrf_failed")).toBe("The settings were not saved. Try again.");
    expect(saveFailureText(403, "forbidden")).toContain("sign in as the admin");
  });
});

describe("mapProblems", () => {
  it("turns the server's field names into the form's", () => {
    const mapped = mapProblems([
      { field: "body.shifts.1.label", message: "A label is 1 to 40 characters." },
      { field: "body.timezone", message: "Not a zone." },
      { field: "body.units.weight", message: "No." },
      { field: "body.shifts.2", message: "Ends when it starts." },
      { field: "body", message: "Shifts must cover 24 hours." },
      { field: "body.note_formats", message: "Unknown." },
    ]);
    expect(mapped.fields.map((f) => f.name)).toEqual([
      "shifts.1.label",
      "timezone",
      "weight",
      "shifts.2.ends_local",
    ]);
    expect(mapped.table).toEqual(["Shifts must cover 24 hours."]);
    expect(mapped.other).toEqual(["Unknown."]);
  });
});
