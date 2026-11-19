import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { StrictMode } from "react";
import { describe, expect, it } from "vitest";
import { api } from "./api/client";
import { App } from "./App";
import { createQueryClient } from "./app/queryClient";
import { createHandlers } from "./mocks/handlers";
import { sessionKey } from "./session/session";
import { server } from "./test/setup";

describe("App", () => {
  it("sends the cached session's CSRF token with a write, under StrictMode", async () => {
    server.use(...createHandlers());
    let token: string | null = null;
    server.use(
      http.put("*/api/v1/health", ({ request }) => {
        token = request.headers.get("X-CSRF-Token");
        return HttpResponse.json({});
      }),
    );
    const queryClient = createQueryClient();
    queryClient.setQueryData(sessionKey, {
      kind: "persona",
      gate: "open",
      csrf_token: "token-from-the-kept-client",
    });
    window.history.replaceState(null, "", "/sign-in");
    render(
      <StrictMode>
        <App queryClient={queryClient} />
      </StrictMode>,
    );
    await screen.findAllByRole("status");
    await api.PUT("/api/v1/health" as never, {} as never);
    expect(token).toBe("token-from-the-kept-client");
  });
});
