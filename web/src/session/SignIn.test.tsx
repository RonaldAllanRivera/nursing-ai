import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { renderApp } from "../test/render";

describe("sign-in screen", () => {
  it("groups the personas by facility and leads with the role", async () => {
    await renderApp("/sign-in");
    const ph = await screen.findByRole("group", { name: "SYNTHETIC Demo Hospital (PH)" });
    expect(
      within(ph).getByRole("button", { name: "Staff nurse · Sarah Navarro, RN" }),
    ).toBeInTheDocument();
    expect(
      within(ph).getByRole("button", { name: "Head nurse · Grace Villareal, RN" }),
    ).toBeInTheDocument();
    const us = screen.getByRole("group", { name: "SYNTHETIC Demo Hospital (US)" });
    expect(within(us).getAllByRole("button")).toHaveLength(2);
    const every = screen.getByRole("group", { name: "Every facility" });
    expect(
      within(every).getByRole("button", { name: "Admin · Victor Lazaro" }),
    ).toBeInTheDocument();
    expect(await screen.findByText("API: healthy")).toBeInTheDocument();
  });

  it("signs a nurse in and lands on the patient list", async () => {
    await renderApp("/sign-in");
    await userEvent.click(
      await screen.findByRole("button", { name: "Staff nurse · Sarah Navarro, RN" }),
    );
    expect(await screen.findByRole("heading", { name: "Patients on this ward" })).toBeVisible();
  });

  it("signs the admin in and lands on settings", async () => {
    await renderApp("/sign-in");
    await userEvent.click(await screen.findByRole("button", { name: "Admin · Victor Lazaro" }));
    expect(await screen.findByRole("heading", { name: "Settings" })).toBeVisible();
  });

  it("never shows the last person's patients to the next person who signs in", async () => {
    const { router } = await renderApp("/sign-in");
    await userEvent.click(
      await screen.findByRole("button", { name: "Staff nurse · Sarah Navarro, RN" }),
    );
    expect(await screen.findAllByRole("link", { name: /Demo patient/ })).toHaveLength(2);
    // Back to sign-in while still signed in, then pick the US nurse straight away.
    await router.navigate({ to: "/sign-in" });
    await userEvent.click(
      await screen.findByRole("button", { name: "Staff nurse · Emily Carter, RN" }),
    );
    expect(await screen.findByRole("heading", { name: "Patients on this unit" })).toBeVisible();
    await waitFor(() => {
      expect(screen.getAllByRole("link", { name: /Demo patient/ })).toHaveLength(1);
    });
  });
});
