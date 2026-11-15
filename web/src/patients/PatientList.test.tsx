import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { renderApp } from "../test/render";

async function signInAs(name: string) {
  await renderApp("/sign-in");
  await userEvent.click(await screen.findByRole("button", { name }));
}

describe("patient list", () => {
  it("lists the ward's patients with bed, name, age and sex", async () => {
    await signInAs("Staff nurse · Sarah Navarro, RN");
    expect(await screen.findByRole("heading", { name: "Patients on this ward" })).toBeVisible();
    const rows = await screen.findAllByRole("link", { name: /Demo patient/ });
    expect(rows).toHaveLength(2);
    const first = rows[0];
    if (!first) throw new Error("no row");
    expect(within(first).getByText("Bed")).toBeInTheDocument();
    expect(within(first).getByText("12")).toBeInTheDocument();
    expect(within(first).getByText("Demo patient A")).toBeInTheDocument();
    expect(within(first).getByText("Synthetic")).toBeInTheDocument();
    expect(within(first).getByText("64 F")).toBeInTheDocument();
    expect(within(first).getByText("Medical Ward")).toBeInTheDocument();
    expect(first).toHaveAttribute("href", expect.stringMatching(/^\/patients\/[0-9a-f-]{36}$/));
  });

  it("shows the shift range under the heading in the facility's clock", async () => {
    await signInAs("Staff nurse · Sarah Navarro, RN");
    expect(await screen.findByText("22:00 11 Nov to 06:00 12 Nov 2026")).toBeVisible();
  });

  it("uses the facility's words: room and unit for the US", async () => {
    await signInAs("Staff nurse · Emily Carter, RN");
    expect(await screen.findByRole("heading", { name: "Patients on this unit" })).toBeVisible();
    const rows = await screen.findAllByRole("link", { name: /Demo patient/ });
    expect(within(rows[0] as HTMLElement).getByText("Room")).toBeInTheDocument();
  });

  it("opens a patient's placeholder page", async () => {
    await signInAs("Staff nurse · Sarah Navarro, RN");
    await userEvent.click(await screen.findByRole("link", { name: /Demo patient B/ }));
    expect(await screen.findByRole("heading", { name: "Demo patient B" })).toBeVisible();
  });
});
