import { describe, expect, it } from "vitest";
import { demoApi } from "../mocks/demo-api";
import { groupPersonas, personaLabel, roleLabel } from "./personas";

describe("personas", () => {
  it("names the roles in plain words", () => {
    expect(roleLabel("staff_nurse")).toBe("Staff nurse");
    expect(roleLabel("head_nurse")).toBe("Head nurse");
    expect(roleLabel("admin")).toBe("Admin");
  });

  it("leads a persona's label with the role", () => {
    const sarah = demoApi.personas[0];
    if (!sarah) throw new Error("no persona");
    expect(personaLabel(sarah)).toBe("Staff nurse · Sarah Navarro, RN");
  });

  it("groups by facility name and puts the admin under Every facility last", () => {
    const groups = groupPersonas(demoApi.personas);
    expect(groups.map((g) => g.heading)).toEqual([
      "SYNTHETIC Demo Hospital (PH)",
      "SYNTHETIC Demo Hospital (US)",
      "Every facility",
    ]);
    expect(groups[2]?.personas.map((p) => p.role)).toEqual(["admin"]);
    expect(groups[0]?.personas).toHaveLength(2);
  });
});
