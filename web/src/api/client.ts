import createClient from "openapi-fetch";
import type { paths } from "./schema";

// The page's own origin, so requests stay same-origin (Vite proxies /api in dev) and
// are valid absolute URLs under Vitest too.
export const api = createClient<paths>({ baseUrl: globalThis.location.origin });
