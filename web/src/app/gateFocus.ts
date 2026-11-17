import { useEffect, useLayoutEffect, useRef, type RefObject } from "react";

/** Marks the gate screen's own elements, which are never the page's focus to give back. */
export const GATE_ATTRIBUTE = "data-gate";

/**
 * A gate screen replaces the page, so the page's focused element is gone when the gate arrives and
 * the PIN field's is gone when it leaves. This remembers the page element that had the focus
 * (by its id), and when the gate goes, puts the focus back on it if it is on the page again (the
 * rough note box, say), otherwise on the page itself, so a keyboard user's next Tab starts at the
 * page and a screen reader has somewhere to be.
 */
export function useRestoreFocusAfterGate(gateUp: boolean, page: RefObject<HTMLElement | null>) {
  const lastId = useRef<string | null>(null);
  const wasUp = useRef(gateUp);

  useEffect(() => {
    const onFocus = (event: FocusEvent) => {
      const target = event.target;
      if (!(target instanceof HTMLElement) || target.closest(`[${GATE_ATTRIBUTE}]`)) return;
      if (page.current?.contains(target) && target.id) lastId.current = target.id;
    };
    document.addEventListener("focusin", onFocus);
    return () => {
      document.removeEventListener("focusin", onFocus);
    };
  }, [page]);

  // Layout effect: the page is already in the DOM (same commit), so the focus never visibly jumps.
  useLayoutEffect(() => {
    if (wasUp.current && !gateUp) {
      const back = lastId.current === null ? null : document.getElementById(lastId.current);
      (back && page.current?.contains(back) ? back : page.current)?.focus();
    }
    wasUp.current = gateUp;
  }, [gateUp, page]);
}
