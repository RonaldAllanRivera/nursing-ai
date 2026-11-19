import { useIsFetching, useIsMutating } from "@tanstack/react-query";
import { isWaking } from "../api/waking";

/**
 * One line on every screen while the database wakes up. The element is always there and only its text
 * changes, so a screen reader hears it appear. It is a wait, not a problem: neutral ink.
 */
export function WakingNotice() {
  const reading = useIsFetching({ predicate: (query) => isWaking(query.state.fetchFailureReason) });
  const writing = useIsMutating({
    predicate: (mutation) => isWaking(mutation.state.failureReason),
  });
  return (
    <p id="waking-notice" role="status" className="text-14 text-ink-2 px-4">
      {reading + writing > 0 ? "Waking the demo database…" : ""}
    </p>
  );
}
