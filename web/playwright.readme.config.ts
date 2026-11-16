import { defineConfig } from "@playwright/test";

// The README's pictures (`make readme-media`): the real stack in replay mode, a short video of the
// Philippine flow and a few screenshots. Never part of `make e2e`: it rewrites files in docs/media.
const webPort = process.env["WEB_PORT"];
if (!webPort) {
  throw new Error("Set WEB_PORT to the web app's port, e.g. `make readme-media PORT_OFFSET=1`.");
}
const baseURL = `http://localhost:${webPort}`;

export default defineConfig({
  testDir: "e2e/readme",
  workers: 1,
  timeout: 240_000,
  reporter: "list",
  use: { baseURL, timezoneId: "UTC" },
  projects: [{ name: "readme", use: { browserName: "chromium" } }],
  webServer: {
    command: "pnpm dev",
    url: baseURL,
    reuseExistingServer: !process.env["CI"],
  },
});
