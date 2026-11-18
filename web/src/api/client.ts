import createClient, { type Client } from "openapi-fetch";
import type { Session } from "../session/session";
import { csrfHeaders } from "./csrf";
import { noteRequest } from "./requestClock";
import type { components, paths } from "./schema";

/** A facility's settings: a settings save's body without the PIN that proves who saved. */
export type FacilitySettings = Omit<components["schemas"]["FacilityUpdateIn"], "pin">;

/** A request that has not answered after this long is aborted. */
export const REQUEST_TIMEOUT_MS = 10_000;

type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
type Init = { signal?: AbortSignal | null; headers?: Record<string, string> } | undefined;

type SessionSource = () => Session | null | undefined;

let currentSession: SessionSource = () => undefined;

/** Where the client reads the signed-in session from, for the CSRF header. The query client sets this up. */
export function readSessionFrom(source: SessionSource) {
  currentSession = source;
}

// No origin and no `fetch` are captured here: the origin is read from `location`, and the
// global `fetch` looked up, when a request is made. That keeps the client independent of
// module load order (tests patch `fetch` first; the dev server proxies /api on the page's own
// origin, which is also what makes it a valid absolute URL under Vitest).
const base = createClient<paths>({
  baseUrl: "",
  fetch: (request) => globalThis.fetch(request),
});

/** The two requests that prove the PIN: the server swaps the session's cookie when it handles one. */
const PIN_PROOF_URLS: readonly string[] = ["/api/v1/session/pin", "/api/v1/session/unlock"];
const SESSION_URL = "/api/v1/session";

type Answer = { response: Response };

/** The PIN proofs that have not answered yet. A 401 that may be the old cookie waits for these. */
const pinProofsOut = new Set<Promise<Answer>>();

/** One request, with the timeout and the caller's abort. The CSRF header is read now, so a retry sends the current one. */
async function once(name: Method, url: string, init: Init): Promise<Answer> {
  noteRequest(name, url);
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
  const call = base[name] as unknown as (url: string, init: object) => Promise<Answer>;
  try {
    return await call(url, {
      baseUrl: globalThis.location.origin,
      ...init,
      headers: { ...csrfHeaders(name, currentSession()), ...init?.headers },
      signal: controller.signal,
    });
  } finally {
    // Noted again when it settles: the server stamps its idle clock when it handles a request,
    // which can be well after it was sent (a slow or waking server), and always before it answers.
    // A timed-out or aborted one may have been handled too. Over-counting only locks later.
    noteRequest(name, url);
    clearTimeout(timer);
    caller?.removeEventListener("abort", forward);
  }
}

/**
 * A 401 may only mean the request left with the cookie that a PIN proof has just swapped. So a 401
 * is checked once before it counts: wait for any PIN proof in flight, then ask who is signed in.
 * Only "nobody" lets the 401 stand (and the caller signs her out). A request that failed is asked
 * again once if she is still signed in: a 401 means the server refused before doing anything, so
 * a second try cannot write twice. A 401 from the PIN proofs themselves is final.
 */
async function checkedBefore401Counts(name: Method, url: string, init: Init, first: Answer) {
  await Promise.allSettled([...pinProofsOut]);
  const signal = init?.signal ? { signal: init.signal } : undefined;
  const reread = await once("GET", SESSION_URL, signal);
  if (name === "GET" && url === SESSION_URL) return reread;
  return reread.response.ok ? once(name, url, init) : first;
}

function method<M extends Method>(name: M): Client<paths>[M] {
  const send = async (url: string, init: Init) => {
    if (name === "POST" && PIN_PROOF_URLS.includes(url)) {
      const answer = once(name, url, init);
      pinProofsOut.add(answer);
      try {
        return await answer;
      } finally {
        pinProofsOut.delete(answer);
      }
    }
    const first = await once(name, url, init);
    return first.response.status === 401 ? checkedBefore401Counts(name, url, init, first) : first;
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
