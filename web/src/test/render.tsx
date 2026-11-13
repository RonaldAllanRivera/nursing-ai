import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { createMemoryHistory } from "@tanstack/react-router";
import { render } from "@testing-library/react";
import { createAppRouter } from "../app/router";
import { createHandlers } from "../mocks/handlers";
import { server } from "./setup";

/** Mounts the whole app at `path`, with a fresh query client, memory history and the mock API. */
export async function renderApp(path = "/") {
  server.use(...createHandlers());
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
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
