import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import { renderApp } from "../test/render";
import { server } from "../test/setup";
import { DEMO_PIN } from "../test/signIn";

afterEach(() => {
  server.events.removeAllListeners();
});

describe("the facility is not asked for before the PIN", () => {
  it("sends no facility read while the PIN screen is up, and one once the gate opens", async () => {
    const asked: string[] = [];
    server.events.on("request:start", ({ request }) => {
      const { pathname } = new URL(request.url);
      if (pathname.startsWith("/api/v1/facilities/")) asked.push(pathname);
    });
    await renderApp("/sign-in");
    await userEvent.click(
      await screen.findByRole("button", { name: "Staff nurse · Sarah Navarro, RN" }),
    );
    const field = await screen.findByLabelText("PIN");
    // Let anything the Shell starts after the session lands go out.
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(asked).toEqual([]);
    await userEvent.type(field, `${DEMO_PIN}{Enter}`);
    await waitFor(() => {
      expect(asked.length).toBeGreaterThan(0);
    });
  });
});
