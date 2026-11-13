import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { setupServer } from "msw/node";
import { afterAll, afterEach } from "vitest";

export const server = setupServer();

// jsdom has no scrolling; the router calls this on navigation.
window.scrollTo = () => undefined;

// Listen at import time, not in beforeAll: openapi-fetch keeps the global `fetch` it finds
// when the client is created, so MSW must patch it before the app's modules load.
server.listen({ onUnhandledFrame: "error" });

afterEach(() => {
  cleanup();
  server.resetHandlers();
});
afterAll(() => {
  server.close();
});
