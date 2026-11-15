import { defineConfig } from "@playwright/test";
import { widths } from "./e2e/widths.ts";

// The screens against the mock API (`pnpm dev:mock`): no backend needed.
// Run with `WEB_PORT=5203 pnpm e2e:mock` (never port 5173).
// WEB_PORT has no default: another container may own 5173, and reuseExistingServer would then
// run this suite against that container's app.
const webPort = process.env["WEB_PORT"];
if (!webPort) {
  throw new Error("Set WEB_PORT to a free port for the mock e2e run, e.g. WEB_PORT=5203.");
}
const baseURL = `http://localhost:${webPort}`;

export default defineConfig({
  testDir: "e2e/mock",
  forbidOnly: !!process.env["CI"],
  reporter: process.env["CI"] ? [["html", { open: "never" }], ["list"]] : "list",
  // The browser's zone is UTC, which is neither facility's: a screen that read the browser's
  // zone instead of the facility's would show the wrong times on any host.
  use: { baseURL, timezoneId: "UTC" },
  projects: widths.map(({ name, width, height }) => ({
    name,
    use: { browserName: "chromium", viewport: { width, height } },
  })),
  webServer: {
    command: "pnpm dev:mock",
    url: baseURL,
    reuseExistingServer: !process.env["CI"],
  },
});
