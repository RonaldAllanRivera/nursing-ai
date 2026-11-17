import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { renderApp } from "../test/render";
import { server } from "../test/setup";
import { chooseAndUnlock, signInAsPersona as signInAs } from "../test/signIn";

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

  it("opens the patient's page from the list", async () => {
    await signInAs("Staff nurse · Sarah Navarro, RN");
    await userEvent.click(await screen.findByRole("link", { name: /Demo patient B/ }));
    expect(await screen.findByRole("heading", { name: "Demo patient B" })).toBeVisible();
  });

  it("says so when the facility does not load, instead of a skeleton forever", async () => {
    await renderApp("/sign-in");
    server.use(http.get("*/api/v1/facilities/:key", () => HttpResponse.json({}, { status: 500 })));
    await chooseAndUnlock("Staff nurse · Sarah Navarro, RN");
    expect(
      await screen.findByText("The ward details did not load. Reload the page to try again."),
    ).toBeVisible();
  });

  it("keeps the rows on screen when a refresh of the list fails", async () => {
    const { queryClient } = await signInAs("Staff nurse · Sarah Navarro, RN");
    expect(await screen.findAllByRole("link", { name: /Demo patient/ })).toHaveLength(2);
    server.use(http.get("*/api/v1/patients", () => HttpResponse.json({}, { status: 500 })));
    await queryClient.invalidateQueries({ queryKey: ["patients"] });
    await waitFor(() => {
      expect(queryClient.getQueryState(["patients"])?.fetchStatus).toBe("idle");
    });
    expect(queryClient.getQueryState(["patients"])?.status).toBe("error");
    expect(screen.getAllByRole("link", { name: /Demo patient/ })).toHaveLength(2);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("keeps the ward on screen when a refresh of the facility fails", async () => {
    const { queryClient } = await signInAs("Staff nurse · Sarah Navarro, RN");
    expect(await screen.findAllByRole("link", { name: /Demo patient/ })).toHaveLength(2);
    server.use(http.get("*/api/v1/facilities/:key", () => HttpResponse.json({}, { status: 500 })));
    await queryClient.invalidateQueries({ queryKey: ["facility"] });
    await act(() => new Promise((resolve) => setTimeout(resolve, 20)));
    expect(queryClient.getQueryState(["facility", "ph-demo"])?.status).toBe("error");
    expect(screen.getByRole("heading", { name: "Patients on this ward" })).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
