import createClient, { type Client } from "openapi-fetch";
import type { paths } from "./schema";

/** A request that has not answered after this long is aborted. */
export const REQUEST_TIMEOUT_MS = 10_000;

type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
type Init = { signal?: AbortSignal | null } | undefined;

// No origin and no `fetch` are captured here: the origin is read from `location`, and the
// global `fetch` looked up, when a request is made. That keeps the client independent of
// module load order (tests patch `fetch` first; the dev server proxies /api on the page's own
// origin, which is also what makes it a valid absolute URL under Vitest).
const base = createClient<paths>({
  baseUrl: "",
  fetch: (request) => globalThis.fetch(request),
});

function method<M extends Method>(name: M): Client<paths>[M] {
  const send = async (url: string, init: Init) => {
    // One controller per request. The timeout always applies; the caller's abort (TanStack
    // Query passes one to every queryFn) is forwarded into it. No AbortSignal.any: Safari 17.4+.
    const controller = new AbortController();
    const timer = setTimeout(() => {
      controller.abort(new DOMException("The request took too long.", "TimeoutError"));
    }, REQUEST_TIMEOUT_MS);
    const caller = init?.signal;
    const forward = () => {
      controller.abort(caller?.reason);
    };
    if (caller?.aborted) forward();
    else caller?.addEventListener("abort", forward, { once: true });
    const call = base[name] as unknown as (url: string, init: object) => Promise<unknown>;
    try {
      return await call(url, {
        baseUrl: globalThis.location.origin,
        ...init,
        signal: controller.signal,
      });
    } finally {
      clearTimeout(timer);
      caller?.removeEventListener("abort", forward);
    }
  };
  return send as unknown as Client<paths>[M];
}

export const api = {
  GET: method("GET"),
  POST: method("POST"),
  PUT: method("PUT"),
  PATCH: method("PATCH"),
  DELETE: method("DELETE"),
};
