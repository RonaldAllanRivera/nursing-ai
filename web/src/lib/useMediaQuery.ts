import { useCallback, useSyncExternalStore } from "react";

/**
 * Whether a media query matches now, and again whenever it changes. Without `matchMedia` (an
 * old browser, a test) it is `fallback`.
 */
export function useMediaQuery(query: string, fallback = true): boolean {
  // A stable function: a new one each render would unsubscribe and subscribe again every time.
  const subscribe = useCallback(
    (onChange: () => void) => {
      if (typeof window.matchMedia !== "function") return () => undefined;
      const list = window.matchMedia(query);
      list.addEventListener("change", onChange);
      return () => {
        list.removeEventListener("change", onChange);
      };
    },
    [query],
  );
  return useSyncExternalStore(
    subscribe,
    () => (typeof window.matchMedia === "function" ? window.matchMedia(query).matches : fallback),
    () => fallback,
  );
}
