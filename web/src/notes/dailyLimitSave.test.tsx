import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { readMockOptions } from "../mocks/options";
import { openPatientA } from "./draftingKit";

describe("Save note at the daily draft limit", () => {
  it("reads the dailyLimit mock option", () => {
    expect(readMockOptions({ dailyLimit: true })).toEqual({ dailyLimit: true });
    expect(readMockOptions({ dailyLimit: "yes" })).toEqual({});
  });

  it("says the daily limit is reached, not that the note was not accepted", async () => {
    await openPatientA({ dailyLimit: true });
    await userEvent.click(screen.getByLabelText("Your note"));
    await userEvent.paste("pt c/o hilo");
    await userEvent.click(screen.getByRole("button", { name: "Save note" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("You've reached today's draft limit. Try again tomorrow.");
    expect(alert).toHaveTextContent("Your note is still here.");
    expect(screen.queryByText(/was not accepted/)).toBeNull();
    expect(screen.getByLabelText("Your note")).toHaveValue("pt c/o hilo");
  });
});
