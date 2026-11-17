import { setupWorker } from "msw/browser";
import { demoApi } from "./demo-api";
import { createHandlers } from "./handlers";
import { MOCK_OPTIONS_GLOBAL, readMockOptions } from "./options";

/**
 * The mock API in the browser, for `pnpm dev:mock`, `pnpm e2e:mock` and working on screens without
 * the API. A Playwright spec changes it with `page.addInitScript` setting `__SOURCELINE_MOCK__`.
 */
export const worker = setupWorker(
  ...createHandlers(
    demoApi,
    readMockOptions((globalThis as Record<string, unknown>)[MOCK_OPTIONS_GLOBAL]),
  ),
);
