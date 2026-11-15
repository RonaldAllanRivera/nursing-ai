import { describe, expect, it } from "vitest";
import { demoApi } from "../mocks/demo-api";
import { mapProblems, settingsSchema, toFormValues, toSettings } from "./form";

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

  it("accepts both demo facilities' values", () => {
    for (const facility of [ph, us]) {
      if (!facility) throw new Error("no demo facility");
      expect(settingsSchema().safeParse(toFormValues(facility)).success).toBe(true);
    }
  });

  it("says no to a timezone that is not in the list, an empty name and a long label", () => {
    if (!ph) throw new Error("no demo facility");
    const values = toFormValues(ph);
    const result = settingsSchema().safeParse({
      ...values,
      name: "  ",
      timezone: "Mars/Olympus",
      shifts: [{ ...(values.shifts[0] ?? {}), label: "x".repeat(41) }],
    });
    expect(result.success).toBe(false);
    const paths = result.error?.issues.map((i) => i.path.join(".")) ?? [];
    expect(paths).toEqual(["name", "timezone", "shifts.0.label"]);
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
