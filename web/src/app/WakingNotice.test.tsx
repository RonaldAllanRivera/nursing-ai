import { QueryClientProvider, useMutation, useQuery } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
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
});
