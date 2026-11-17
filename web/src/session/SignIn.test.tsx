import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "../test/setup";
import { renderApp } from "../test/render";
import { DEMO_BANNER } from "./signInOptions";

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

  it("keeps the list of people when a refresh of it fails", async () => {
    const { queryClient } = await renderApp("/sign-in");
    expect(
      await screen.findByRole("button", { name: "Staff nurse · Sarah Navarro, RN" }),
    ).toBeVisible();
    server.use(http.get("*/api/v1/personas", () => HttpResponse.json({}, { status: 500 })));
    await queryClient.invalidateQueries({ queryKey: ["personas"] });
    await act(() => new Promise((resolve) => setTimeout(resolve, 20)));
    expect(queryClient.getQueryState(["personas"])?.status).toBe("error");
    expect(screen.getByRole("button", { name: "Staff nurse · Sarah Navarro, RN" })).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("offers Google first as a plain link, with the demo people and their PIN after it", async () => {
    await renderApp("/sign-in", { google: true });
    const link = await screen.findByRole("link", { name: "Sign in with Google" });
    expect(link).toHaveAttribute("href", "/api/v1/auth/google/start");
    expect(screen.getByText("Demo PIN: 135790")).toBeVisible();
    const button = await screen.findByRole("button", { name: "Staff nurse · Sarah Navarro, RN" });
    expect(link.compareDocumentPosition(button) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("shows the demo PIN with the people, and no Google link, when Google is off", async () => {
    await renderApp("/sign-in");
    expect(await screen.findByText("Demo PIN: 135790")).toBeVisible();
    expect(screen.queryByRole("link", { name: "Sign in with Google" })).not.toBeInTheDocument();
  });

  it("shows no PIN line when the demo is off", async () => {
    await renderApp("/sign-in", { demo: false });
    await screen.findByRole("button", { name: "Staff nurse · Sarah Navarro, RN" });
    expect(screen.queryByText(/Demo PIN/)).not.toBeInTheDocument();
  });

  it.each([
    ["no_access", "You don't have access yet. Ask the admin to invite your Google account."],
    [
      "expired",
      "That sign-in took too long or was started in another tab. Sign in with Google again.",
    ],
    ["cancelled", "Google sign-in was cancelled. Sign in again when you're ready."],
  ])("explains ?error=%s above the choices", async (error, words) => {
    await renderApp(`/sign-in?error=${error}`, { google: true });
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(words);
    const link = await screen.findByRole("link", { name: "Sign in with Google" });
    expect(alert.compareDocumentPosition(link) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("says nothing for an error value it does not know", async () => {
    await renderApp("/sign-in?error=boom", { google: true });
    await screen.findByRole("link", { name: "Sign in with Google" });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("clears the refusal when a person is chosen", async () => {
    const { router } = await renderApp("/sign-in?error=expired", { google: true });
    await userEvent.click(
      await screen.findByRole("button", { name: "Staff nurse · Sarah Navarro, RN" }),
    );
    expect(await screen.findByRole("heading", { name: "Patients on this ward" })).toBeVisible();
    expect(router.state.location.search).not.toHaveProperty("error");
  });

  it("clears the refusal when the Google link is followed", async () => {
    const { router } = await renderApp("/sign-in?error=no_access", { google: true });
    const link = await screen.findByRole("link", { name: "Sign in with Google" });
    link.addEventListener("click", (event) => {
      event.preventDefault();
    });
    await userEvent.click(link);
    await waitFor(() => {
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });
    expect(router.state.location.search).not.toHaveProperty("error");
  });

  it("falls back to the people alone when the options do not load", async () => {
    await renderApp("/sign-in", { google: true }, [
      http.get("*/api/v1/sign-in-options", () => HttpResponse.json({}, { status: 501 })),
    ]);
    expect(
      await screen.findByRole("button", { name: "Staff nurse · Sarah Navarro, RN" }),
    ).toBeVisible();
    expect(screen.queryByRole("link", { name: "Sign in with Google" })).not.toBeInTheDocument();
    expect(screen.queryByText(/Demo PIN/)).not.toBeInTheDocument();
    expect(screen.queryByText(DEMO_BANNER)).not.toBeInTheDocument();
  });
});
