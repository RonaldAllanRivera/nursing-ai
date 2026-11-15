import { defineConfig } from "@playwright/test";
import { widths } from "./e2e/widths.ts";

const baseURL = `http://localhost:${process.env["WEB_PORT"] ?? "5173"}`;

export default defineConfig({
  testDir: "e2e",
  testIgnore: ["mock/**"],
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
