import { setupWorker } from "msw/browser";
import { createHandlers } from "./handlers";

/** The mock API in the browser, for `pnpm dev:mock`, `pnpm e2e:mock` and working on screens without the API. */
export const worker = setupWorker(...createHandlers());
