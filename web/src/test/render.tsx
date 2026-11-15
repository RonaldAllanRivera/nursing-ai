import { QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { render } from "@testing-library/react";
import { createQueryClient } from "../app/queryClient";
import { createAppRouter } from "../app/router";
import { createHandlers } from "../mocks/handlers";
import { server } from "./setup";

/** Mounts the whole app at `path`, with a fresh query client, memory history and the mock API. */
export async function renderApp(path = "/") {
  server.use(...createHandlers());
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
