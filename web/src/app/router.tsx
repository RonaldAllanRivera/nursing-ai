import type { QueryClient } from "@tanstack/react-query";
import {
  createRootRouteWithContext,
  createRoute,
  createRouter,
  Outlet,
  type RouterHistory,
} from "@tanstack/react-router";
import { HealthStatus } from "../health/HealthStatus";

export interface RouterContext {
  queryClient: QueryClient;
}

const rootRoute = createRootRouteWithContext<RouterContext>()({
  component: Outlet,
});

// Today's start page. W2 replaces it with the "send you on" redirect.
const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: function StartPage() {
    return (
      <main>
        <h1>Nursing Documentation AI</h1>
        <HealthStatus />
        <p>Documentation aid — the nurse reviews and signs every note.</p>
      </main>
    );
  },
});

const routeTree = rootRoute.addChildren([indexRoute]);

/** Tests pass a memory history to mount any path; the app passes none (the browser's). */
export function createAppRouter({
  history,
  queryClient,
}: {
  history?: RouterHistory;
  queryClient: QueryClient;
}) {
  return createRouter({
    routeTree,
    context: { queryClient },
    ...(history ? { history } : {}),
  });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof createAppRouter>;
  }
}
