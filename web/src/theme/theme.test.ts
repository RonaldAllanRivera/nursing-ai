import { afterEach, describe, expect, it, vi } from "vitest";
import { applyTheme, readTheme, saveTheme } from "./theme";

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

describe("theme", () => {
  it("defaults to day", () => {
    expect(readTheme()).toBe("day");
  });

  it("remembers night and puts it on <html>", () => {
    saveTheme("night");
    applyTheme("night");
    expect(readTheme()).toBe("night");
    expect(document.documentElement.dataset["theme"]).toBe("night");
  });

  it("survives a localStorage that throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(readTheme()).toBe("day");
    expect(() => {
      saveTheme("night");
    }).not.toThrow();
  });
});
