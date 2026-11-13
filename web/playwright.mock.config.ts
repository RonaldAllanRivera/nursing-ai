import { defineConfig } from "@playwright/test";

// The screens against the mock API (`pnpm dev:mock`): no backend needed.
// Run with `WEB_PORT=5203 pnpm e2e:mock` (never port 5173).
const baseURL = `http://localhost:${process.env["WEB_PORT"] ?? "5173"}`;

const widths = [
  { name: "chromium-375", width: 375, height: 812 },
  { name: "chromium-768", width: 768, height: 1024 },
  { name: "chromium-1280", width: 1280, height: 800 },
];

export default defineConfig({
  testDir: "e2e/mock",
  forbidOnly: !!process.env["CI"],
  reporter: process.env["CI"] ? [["html", { open: "never" }], ["list"]] : "list",
  use: { baseURL },
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
