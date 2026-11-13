import { describe, expect, it } from "vitest";
import { words } from "./words";

describe("words", () => {
  it("labels the format DAR for en-US", () => {
    expect(words("en-US").noteFormat("fdar")).toBe("DAR");
  });

  it("labels the format FDAR for en-PH", () => {
    expect(words("en-PH").noteFormat("fdar")).toBe("FDAR");
  });

  it("gives both locales every key", () => {
    expect(Object.keys(words("en-US")).sort()).toEqual(Object.keys(words("en-PH")).sort());
  });

  it("uses ward words for en-PH and unit words for en-US", () => {
    expect(words("en-PH").ward).toBe("Ward");
    expect(words("en-US").ward).toBe("Unit");
    expect(words("en-PH").patientsHeading).toBe("Patients on this ward");
    expect(words("en-US").patientsHeading).toBe("Patients on this unit");
    expect(words("en-US").recordNumber).toBe("MRN");
    expect(words("en-PH").recordNumber).toBe("Hospital no.");
  });
});
