import { defineConfig } from "@playwright/test";

const baseURL = `http://localhost:${process.env["WEB_PORT"] ?? "5173"}`;

const widths = [
  { name: "chromium-375", width: 375, height: 812 },
  { name: "chromium-768", width: 768, height: 1024 },
  { name: "chromium-1280", width: 1280, height: 800 },
];

export default defineConfig({
  testDir: "e2e",
  forbidOnly: !!process.env["CI"],
  reporter: process.env["CI"] ? [["html", { open: "never" }], ["list"]] : "list",
  use: { baseURL },
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
