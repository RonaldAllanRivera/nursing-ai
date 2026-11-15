import { describe, expect, it } from "vitest";
import { checkShifts, type ShiftTimes } from "./checkShifts";

const s = (code: string, starts: string, ends: string): ShiftTimes => ({
  code,
  starts_local: starts,
  ends_local: ends,
});

const PH = [s("6-2", "06:00", "14:00"), s("2-10", "14:00", "22:00"), s("10-6", "22:00", "06:00")];
const US = [s("7a-7p", "07:00", "19:00"), s("7p-7a", "19:00", "07:00")];

describe("checkShifts", () => {
  it("accepts both presets", () => {
    expect(checkShifts(PH, "06:00", "24h")).toEqual([]);
    expect(checkShifts(US, "07:00", "24h")).toEqual([]);
  });

  it("flags a gap and an overlap", () => {
    const gap = [s("6-2", "06:00", "14:00"), s("2-10", "15:00", "22:00"), PH[2] as ShiftTimes];
    expect(checkShifts(gap, "06:00", "24h")).toEqual(["There's a gap between 14:00 and 15:00."]);
    const overlap = [
      s("6-2", "06:00", "14:00"),
      s("2-10", "14:00", "22:00"),
      s("10-6", "21:00", "06:00"),
    ];
    expect(checkShifts(overlap, "06:00", "24h")).toEqual([
      "The 2-10 and 10-6 shifts overlap from 21:00 to 22:00.",
    ]);
  });

  it("finds a gap across midnight", () => {
    const shifts = [
      s("6-2", "06:00", "14:00"),
      s("2-10", "14:00", "22:00"),
      s("10-6", "22:00", "05:00"),
    ];
    expect(checkShifts(shifts, "06:00", "24h")).toEqual(["There's a gap between 05:00 and 06:00."]);
  });

  it("says when the shifts do not cover the day", () => {
    expect(checkShifts([s("day", "07:00", "19:00")], "07:00", "24h")).toEqual([
      "There's a gap between 19:00 and 07:00.",
    ]);
  });

  it("says when the day does not start where a shift starts", () => {
    expect(checkShifts(PH, "07:00", "24h")).toEqual([
      "The nursing day must start when one of the shifts starts.",
    ]);
  });

  it("flags a repeated code", () => {
    const shifts = [s("A", "06:00", "14:00"), s("A", "14:00", "06:00")];
    expect(checkShifts(shifts, "06:00", "24h")).toEqual([
      "Two shifts use the code A. Give each shift its own code.",
    ]);
  });

  it("flags a shift that ends when it starts", () => {
    const shifts = [s("A", "06:00", "06:00"), s("B", "06:00", "06:00")];
    expect(checkShifts(shifts, "06:00", "24h")).toContain(
      "The A shift ends when it starts. Give it a different end time.",
    );
  });

  it("asks for a shift when there are none", () => {
    expect(checkShifts([], "06:00", "24h")).toEqual(["Add at least one shift."]);
  });

  it("leaves out a shift whose times are not filled in yet", () => {
    expect(checkShifts([s("A", "", "14:00")], "06:00", "24h")).toEqual([]);
  });

  it("words the times in the facility's clock", () => {
    const gap = [s("6-2", "06:00", "14:00"), s("2-10", "15:00", "22:00"), PH[2] as ShiftTimes];
    expect(checkShifts(gap, "06:00", "12h")).toEqual(["There's a gap between 2 PM and 3 PM."]);
    const half = [s("6-2", "06:00", "14:30"), s("2-10", "15:00", "22:00"), PH[2] as ShiftTimes];
    expect(checkShifts(half, "06:00", "12h")).toEqual(["There's a gap between 2:30 PM and 3 PM."]);
    const overlap = [
      s("6-2", "06:00", "14:00"),
      s("2-10", "14:00", "22:00"),
      s("10-6", "21:00", "06:00"),
    ];
    expect(checkShifts(overlap, "06:00", "12h")).toEqual([
      "The 2-10 and 10-6 shifts overlap from 9 PM to 10 PM.",
    ]);
  });

  it("gives the general line when one shift spans another", () => {
    const spanning = [s("A", "06:00", "22:00"), s("B", "14:00", "18:00"), s("C", "22:00", "06:00")];
    expect(checkShifts(spanning, "06:00", "24h")).toEqual([
      "Together the shifts must cover 24 hours with no gap or overlap.",
    ]);
  });

  it("never says the same thing twice", () => {
    const twins = [s("A", "06:00", "06:00"), s("A", "06:00", "06:00")];
    const problems = checkShifts(twins, "06:00", "24h");
    expect(new Set(problems).size).toBe(problems.length);
  });
});
