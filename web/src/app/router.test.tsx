import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "../test/setup";
import { renderApp } from "../test/render";

describe("app router", () => {
  it("shows the sign-in page with the health line and the aid line", async () => {
    await renderApp("/sign-in");
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeVisible();
    expect(
      screen.getByText("Documentation aid — the nurse reviews and signs every note."),
    ).toBeInTheDocument();
    expect(await screen.findByText("API: healthy")).toBeInTheDocument();
  });

  it("sends / on to the patients for a nurse", async () => {
    const { router } = await renderApp("/sign-in");
    await userEvent.click(
      await screen.findByRole("button", { name: "Staff nurse · Sarah Navarro, RN" }),
    );
    await screen.findByRole("heading", { name: "Patients on this ward" });
    await router.navigate({ to: "/" });
    expect(await screen.findByRole("heading", { name: "Patients on this ward" })).toBeVisible();
    expect(router.state.location.pathname).toBe("/patients");
  });

  it("sends you to sign-in when a request comes back 401 mid-session", async () => {
    const { queryClient } = await renderApp("/sign-in");
    await userEvent.click(
      await screen.findByRole("button", { name: "Staff nurse · Sarah Navarro, RN" }),
    );
    await screen.findByRole("heading", { name: "Patients on this ward" });
    await screen.findAllByRole("link", { name: /Demo patient/ });
    server.use(
      http.get("*/api/v1/patients", () =>
        HttpResponse.json(
          { type: "about:blank", title: "Not signed in", status: 401, code: "not_signed_in" },
          { status: 401, headers: { "Content-Type": "application/problem+json" } },
        ),
      ),
    );
    await queryClient.invalidateQueries({ queryKey: ["patients"] });
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeVisible();
  });
});
