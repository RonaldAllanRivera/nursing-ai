import { QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { render } from "@testing-library/react";
import type { HttpHandler } from "msw";
import { createQueryClient } from "../app/queryClient";
import { createAppRouter } from "../app/router";
import { demoApi } from "../mocks/demo-api";
import { createHandlers } from "../mocks/handlers";
import type { MockOptions } from "../mocks/options";
import { server } from "./setup";

/** Mounts the whole app at `path`, with a fresh query client, memory history and the mock API (set up with `options`). */
export async function renderApp(
  path = "/",
  options: MockOptions = {},
  /** Handlers that win over the mock's, for a route that must fail. */
  overrides: HttpHandler[] = [],
) {
  server.use(...overrides, ...createHandlers(demoApi, options));
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({
    queries: { ...queryClient.getDefaultOptions().queries, retry: false },
    // A mutation that opts into `retry` (the rough note) still retries, with no waiting.
    mutations: { retry: false, retryDelay: 0 },
  });
  const history = createMemoryHistory({ initialEntries: [path] });
  const router = createAppRouter({ history, queryClient });
  await router.load();
  const result = render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { ...result, router, queryClient };
}
