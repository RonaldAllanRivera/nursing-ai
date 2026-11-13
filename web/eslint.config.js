import js from "@eslint/js";
import { defineConfig } from "eslint/config";
import jsxA11y from "eslint-plugin-jsx-a11y";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default defineConfig(
  {
    ignores: [
      "dist",
      ".claude",
      "node_modules",
      "playwright-report",
      "test-results",
      "src/api/schema.d.ts",
      "src/mocks/demo-api.ts",
    ],
  },
  js.configs.recommended,
  tseslint.configs.strictTypeChecked,
  jsxA11y.flatConfigs.recommended,
  reactHooks.configs.flat.recommended,
  {
    languageOptions: {
      globals: { ...globals.browser, ...globals.node },
      parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname },
    },
  },
  // This file is plain JavaScript outside the TypeScript projects: no type-aware rules.
  { files: ["eslint.config.js"], extends: [tseslint.configs.disableTypeChecked] },
);
