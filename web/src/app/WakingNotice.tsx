import { useIsFetching, useIsMutating } from "@tanstack/react-query";
import { useSlowRequests } from "../api/slowRequests";
import { isWaking } from "../api/waking";

/**
 * One line on every screen while the database wakes up (or any request has waited over 5 s). The element is always there and only its text
 * changes, so a screen reader hears it appear. It is a wait, not a problem: neutral ink.
 */
export function WakingNotice() {
  const reading = useIsFetching({ predicate: (query) => isWaking(query.state.fetchFailureReason) });
  const writing = useIsMutating({
    predicate: (mutation) => isWaking(mutation.state.failureReason),
  });
  const slow = useSlowRequests();
  return (
    <p id="waking-notice" role="status" className="text-14 text-ink-2 px-4">
      {reading + writing + slow > 0 ? "Waking the demo database…" : ""}
    </p>
  );
}
