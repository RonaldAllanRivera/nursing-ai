import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { setupServer } from "msw/node";
import { afterAll, afterEach } from "vitest";

export const server = setupServer();

// jsdom has no scrolling; the router calls this on navigation.
window.scrollTo = () => undefined;

// Listen at import time, not in beforeAll, so MSW has patched the global `fetch` before any test
// runs. (client.ts looks `fetch` up per request, so load order no longer matters.)
server.listen({ onUnhandledFrame: "error" });

afterEach(() => {
  cleanup();
  server.resetHandlers();
});
afterAll(() => {
  server.close();
});
