import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderApp } from "../test/render";

describe("app router", () => {
  it("shows the start page at /", async () => {
    await renderApp("/");
    expect(screen.getByRole("heading", { name: "Nursing Documentation AI" })).toBeInTheDocument();
    expect(
      screen.getByText("Documentation aid — the nurse reviews and signs every note."),
    ).toBeInTheDocument();
    expect(await screen.findByRole("status")).toBeInTheDocument();
  });
});
