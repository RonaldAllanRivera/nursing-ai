import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { configDefaults, defineConfig } from "vitest/config";

const webPort = Number(process.env["WEB_PORT"] ?? 5173);
const apiPort = process.env["API_PORT"] ?? "8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: true,
    strictPort: true,
    port: webPort,
    proxy: { "/api": `http://localhost:${apiPort}` },
  },
  build: { target: "es2023" },
  test: {
    environment: "jsdom",
    setupFiles: ["src/test/setup.ts"],
    exclude: [...configDefaults.exclude, ".claude/**", "e2e/**"],
  },
});
