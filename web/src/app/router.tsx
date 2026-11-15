import type { QueryClient } from "@tanstack/react-query";
import {
  createRootRouteWithContext,
  createRoute,
  createRouter,
  Outlet,
  redirect,
  type RouterHistory,
} from "@tanstack/react-router";
import { NotePage } from "../notes/NotePage";
import { PatientList } from "../patients/PatientList";
import { PatientPage } from "../patients/PatientPage";
import { SettingsPage } from "../settings/SettingsPage";
import { SignIn } from "../session/SignIn";
import { sessionQuery } from "../session/session";
import { Shell } from "./Shell";

export interface RouterContext {
  queryClient: QueryClient;
}

const rootRoute = createRootRouteWithContext<RouterContext>()({
  component: Outlet,
});

/** The session, or a redirect to sign-in. A cached "signed out" answer is kept up to date by the sign-in and sign-out calls and by any 401. */
async function requireSession(queryClient: QueryClient) {
  const session = await queryClient.query({ ...sessionQuery, staleTime: "static" });
  // eslint-disable-next-line @typescript-eslint/only-throw-error -- redirect() is thrown on purpose.
  if (!session) throw redirect({ to: "/sign-in" });
  return session;
}

// "/" sends you on: a nurse to her patients, the admin to settings, nobody to sign-in.
const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  beforeLoad: async ({ context }) => {
    const session = await requireSession(context.queryClient);
    // eslint-disable-next-line @typescript-eslint/only-throw-error -- redirect() is thrown on purpose.
    throw redirect({ to: session.facility_key === null ? "/settings" : "/patients" });
  },
});

const signInRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/sign-in",
  component: SignIn,
});

// Everything signed-in sits under the shell (the header, the aid line).
const appRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: "app",
  beforeLoad: async ({ context }) => {
    await requireSession(context.queryClient);
  },
  component: Shell,
});

async function requireNurse(queryClient: QueryClient) {
  const session = await requireSession(queryClient);
  // eslint-disable-next-line @typescript-eslint/only-throw-error -- redirect() is thrown on purpose.
  if (session.facility_key === null) throw redirect({ to: "/settings" });
}

const patientsRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/patients",
  beforeLoad: ({ context }) => requireNurse(context.queryClient),
  component: PatientList,
});

const patientRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/patients/$patientId",
  beforeLoad: ({ context }) => requireNurse(context.queryClient),
  component: PatientPage,
});

const noteRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/notes/$noteId",
  // `line` is the selected draft line. Its id is opaque: kept as the server wrote it.
  validateSearch: (search: Record<string, unknown>): { line?: string } => {
    // The router's JSON search parser turns a number-looking value into a number before it gets
    // here, so `?line=1.50` arrives as 1.5. Ids the app writes round-trip (they are quoted);
    // only a hand-typed, number-looking id can lose its exact text. Not worth a custom parser.
    const line = search["line"];
    const id = typeof line === "string" || typeof line === "number" ? String(line) : "";
    return id === "" ? {} : { line: id };
  },
  beforeLoad: ({ context }) => requireNurse(context.queryClient),
  component: NotePage,
});

const settingsRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/settings",
  beforeLoad: async ({ context }) => {
    const session = await requireSession(context.queryClient);
    // eslint-disable-next-line @typescript-eslint/only-throw-error -- redirect() is thrown on purpose.
    if (session.facility_key !== null) throw redirect({ to: "/patients" });
  },
  component: SettingsPage,
});

const routeTree = rootRoute.addChildren([
  indexRoute,
  signInRoute,
  appRoute.addChildren([patientsRoute, patientRoute, noteRoute, settingsRoute]),
]);

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
