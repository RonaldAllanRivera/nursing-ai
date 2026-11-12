import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "../test/setup";
import { HealthStatus } from "./HealthStatus";

const HEALTH = "*/api/v1/health";

describe("HealthStatus", () => {
  it('shows "Checking API…" before the answer', () => {
    server.use(http.get(HEALTH, () => HttpResponse.json({ status: "healthy", database: "ok" })));
    render(<HealthStatus />);
    expect(screen.getByText("Checking API…")).toBeInTheDocument();
  });

  it('shows "API: healthy" when the API reports healthy', async () => {
    server.use(http.get(HEALTH, () => HttpResponse.json({ status: "healthy", database: "ok" })));
    render(<HealthStatus />);
    expect(await screen.findByText("API: healthy")).toBeInTheDocument();
  });

  it('shows "API: unhealthy — database unreachable" on a 503', async () => {
    server.use(
      http.get(HEALTH, () =>
        HttpResponse.json({ status: "unhealthy", database: "unreachable" }, { status: 503 }),
      ),
    );
    render(<HealthStatus />);
    expect(await screen.findByText("API: unhealthy — database unreachable")).toBeInTheDocument();
  });

  it('shows "API: unreachable" when the request fails', async () => {
    server.use(http.get(HEALTH, () => HttpResponse.error()));
    render(<HealthStatus />);
    expect(await screen.findByText("API: unreachable")).toBeInTheDocument();
  });

  it("announces the status in a polite live region", () => {
    server.use(http.get(HEALTH, () => HttpResponse.json({ status: "healthy", database: "ok" })));
    render(<HealthStatus />);
    expect(screen.getByRole("status")).toHaveTextContent("Checking API…");
  });
});
