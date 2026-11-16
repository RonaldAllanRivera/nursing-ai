import { defineConfig } from "@playwright/test";
import { widths } from "./e2e/widths.ts";

// The journeys against the real stack (`make e2e`: Postgres and the API in Compose, the Vite dev
// server proxying /api to it). WEB_PORT has no default: another container may own 5173, and
// reuseExistingServer would then run this suite against that container's app.
const webPort = process.env["WEB_PORT"];
if (!webPort) {
  throw new Error("Set WEB_PORT to the web app's port, e.g. `make e2e PORT_OFFSET=1` (5183).");
}
const baseURL = `http://localhost:${webPort}`;

export default defineConfig({
  testDir: "e2e",
  testIgnore: ["mock/**"],
  forbidOnly: !!process.env["CI"],
  reporter: process.env["CI"] ? [["html", { open: "never" }], ["list"]] : "list",
  // One journey at a time: they share one database, and a settings save must not land between
  // another journey's sign-in and its note.
  workers: 1,
  // A draft is made by the API's worker, in the background; replay and live add their own time.
  timeout: 120_000,
  // The browser's zone is UTC, which is neither facility's: a screen that read the browser's
  // zone instead of the facility's would show the wrong times on any host.
  use: { baseURL, timezoneId: "UTC" },
  projects: widths.map(({ name, width, height }) => ({
    name,
    use: { browserName: "chromium", viewport: { width, height } },
  })),
  webServer: {
    command: "pnpm dev",
    url: baseURL,
    reuseExistingServer: !process.env["CI"],
  },
});
