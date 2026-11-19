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
  const stopWaiting = useRef<(() => void) | null>(null);
  useLayoutEffect(() => {
    if (wasUp.current && !gateUp) {
      const was = last.current;
      const wanted = was?.id && was.scope === scope ? was.id : null;
      const back = wanted ? document.getElementById(wanted) : null;
      if (back && page.current?.contains(back)) {
        back.focus();
      } else {
        page.current?.focus();
        // The page was dropped from memory behind the lock and is loading again: the element comes
        // back with its data. Give the focus to it then, unless she has put it somewhere herself.
        if (wanted && page.current) waitFor(wanted, page.current);
      }
    }
    wasUp.current = gateUp;

    function waitFor(id: string, root: HTMLElement) {
      stopWaiting.current?.();
      const stop = () => {
        observer.disconnect();
        clearTimeout(timer);
        document.removeEventListener("focusin", moved);
        stopWaiting.current = null;
      };
      const moved = (event: FocusEvent) => {
        if (event.target !== root) stop();
      };
      const observer = new MutationObserver(() => {
        const found = document.getElementById(id);
        if (found && root.contains(found)) {
          stop();
          found.focus();
        }
      });
      const timer = setTimeout(stop, WAIT_FOR_PAGE_MS);
      observer.observe(root, { childList: true, subtree: true });
      document.addEventListener("focusin", moved);
      stopWaiting.current = stop;
    }
  }, [gateUp, page, scope]);

  useEffect(
    () => () => {
      stopWaiting.current?.();
    },
    [],
  );
}

/** How long the page may take to load again after a lock before the focus stops waiting for it. */
const WAIT_FOR_PAGE_MS = 10_000;
