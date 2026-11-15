import { describe, expect, it } from "vitest";
import { cn } from "./cn";

describe("cn", () => {
  it("keeps a type size and a colour together", () => {
    expect(cn("text-ink text-14")).toBe("text-ink text-14");
    expect(cn("text-14 text-ink-2")).toBe("text-14 text-ink-2");
  });

  it("lets a later size or radius replace an earlier one", () => {
    expect(cn("text-14 text-18")).toBe("text-18");
    expect(cn("rounded-control rounded-full")).toBe("rounded-full");
    expect(cn("rounded-sheet rounded-control")).toBe("rounded-control");
  });
});
