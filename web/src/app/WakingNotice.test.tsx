import { QueryClientProvider, useMutation, useQuery } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import { server } from "../test/setup";
import { ApiError } from "../api/errors";
import { WakingNotice } from "./WakingNotice";
import { createQueryClient } from "./queryClient";

const waking = () =>
  new ApiError(503, { status: 503, code: "database_waking", title: "x", type: "about:blank" });

/** The app's client with the 5 s waits shortened so a test can see the retries. */
function quickClient() {
  const client = createQueryClient();
  client.setDefaultOptions({
    queries: { ...client.getDefaultOptions().queries, retryDelay: 20 },
    mutations: { ...client.getDefaultOptions().mutations, retryDelay: 20 },
  });
  return client;
}

function mount(children: ReactNode) {
  render(
    <QueryClientProvider client={quickClient()}>
      <WakingNotice />
      {children}
    </QueryClientProvider>,
  );
}

describe("WakingNotice", () => {
  it("says the database is waking while a query waits, and is empty after", async () => {
    let tries = 0;
    function Page() {
      const query = useQuery({
        queryKey: ["page"],
        queryFn: () => {
          tries += 1;
          return tries <= 2 ? Promise.reject(waking()) : Promise.resolve("ready");
        },
      });
      return <p>{query.data ?? "loading"}</p>;
    }
    mount(<Page />);
    const status = screen.getByRole("status");
    await waitFor(() => {
      expect(status).toHaveTextContent("Waking the demo database…");
    });
    await screen.findByText("ready");
    await waitFor(() => {
      expect(status).toBeEmptyDOMElement();
    });
    expect(screen.getByRole("status")).toBe(status);
  });

  it("also shows while a write waits", async () => {
    let tries = 0;
    function Writer() {
      const mutation = useMutation({
        mutationFn: () => {
          tries += 1;
          return tries === 1 ? Promise.reject(waking()) : Promise.resolve("ok");
        },
      });
      return (
        <button
          type="button"
          onClick={() => {
            mutation.mutate();
          }}
        >
          go
        </button>
      );
    }
    mount(<Writer />);
    const status = screen.getByRole("status");
    expect(status).toBeEmptyDOMElement();
    screen.getByRole("button").click();
    await waitFor(() => {
      expect(status).toHaveTextContent("Waking the demo database…");
    });
    await waitFor(() => {
      expect(status).toBeEmptyDOMElement();
    });
  });

  it("also shows when any request has been pending for more than 5 s", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    try {
      let answer: () => void = () => undefined;
      server.use(
        http.get(
          "*/api/v1/health",
          () =>
            new Promise<Response>((resolve) => {
              answer = () => {
                resolve(HttpResponse.json({ status: "healthy", database: "ok" }));
              };
            }),
        ),
      );
      mount(null);
      const status = screen.getByRole("status");
      const pending = api.GET("/api/v1/health");
      await vi.advanceTimersByTimeAsync(4_000);
      expect(status).toBeEmptyDOMElement();
      await vi.advanceTimersByTimeAsync(1_500);
      expect(status).toHaveTextContent("Waking the demo database…");
      answer();
      await vi.advanceTimersByTimeAsync(10);
      await pending;
      await vi.advanceTimersByTimeAsync(10);
      expect(status).toBeEmptyDOMElement();
    } finally {
      vi.useRealTimers();
    }
  });
});
