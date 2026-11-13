import { setupWorker } from "msw/browser";
import { handlers } from "./handlers";

/** The mock API in the browser, for `pnpm e2e:mock` and working on screens without the API. */
export const worker = setupWorker(...handlers);
