import { useEffect, useLayoutEffect, useRef, type RefObject } from "react";

/** Marks the gate screen's own elements, which are never the page's focus to give back. */
export const GATE_ATTRIBUTE = "data-gate";

/**
 * A gate screen replaces the page, so the page's focused element is gone when the gate arrives and
 * the PIN field's is gone when it leaves. This remembers where the focus was on the page (by the
 * element's id, or nothing if it had none) and which page that was (`scope`, the address), and
 * when the gate goes puts the focus back on that element if it is on the same page again (the
 * rough note box, say). Otherwise it goes to the page itself, so a keyboard user's next Tab starts
 * at the page and a screen reader has somewhere to be. An id left from an earlier focus, or from
 * another patient's page that has the same ids, is never used.
 */
export function useRestoreFocusAfterGate(
  gateUp: boolean,
  page: RefObject<HTMLElement | null>,
  scope: string,
) {
  const last = useRef<{ id: string | null; scope: string } | null>(null);
  const wasUp = useRef(gateUp);
  const scopeNow = useRef(scope);

  useEffect(() => {
    scopeNow.current = scope;
  }, [scope]);

  useEffect(() => {
    const onFocus = (event: FocusEvent) => {
      const target = event.target;
      if (!(target instanceof HTMLElement) || target.closest(`[${GATE_ATTRIBUTE}]`)) return;
      if (page.current?.contains(target)) {
        last.current = { id: target.id || null, scope: scopeNow.current };
      }
    };
    document.addEventListener("focusin", onFocus);
    return () => {
      document.removeEventListener("focusin", onFocus);
    };
  }, [page]);

  // Layout effect: the page is already in the DOM (same commit), so the focus never visibly jumps.
  useLayoutEffect(() => {
    if (wasUp.current && !gateUp) {
      const was = last.current;
      const back = was?.id && was.scope === scope ? document.getElementById(was.id) : null;
      (back && page.current?.contains(back) ? back : page.current)?.focus();
    }
    wasUp.current = gateUp;
  }, [gateUp, page, scope]);
}
