import { useState } from "react";
import type { components } from "../api/schema";
import { Button } from "../components/ui/Button";
import { draftAgainOutcome, useDraftAgain } from "./draftAgain";

/**
 * "Try drafting again" on one row of the shift list. Each row has its own request, so a tap on
 * another row is never dropped while this one's is out. Its words (the daily limit, no connection)
 * go when the list is read again or the row's job changes (the row remounts).
 */
export function RowDraftAgain({
  patientId,
  roughNoteId,
  listReadAt,
  onStarted,
  onTap,
}: {
  patientId: string;
  roughNoteId: string;
  /** When the list was last read: a new read makes the row's last words stale. */
  listReadAt: number;
  onStarted: (job: components["schemas"]["DraftJobOut"]) => void;
  /** Called on the tap, before the request: the row takes the focus the button is about to lose. */
  onTap: () => void;
}) {
  const again = useDraftAgain(patientId);
  // The words belong to the read of the list they were said after: a newer read makes them stale.
  const [said, setSaid] = useState<{ words: string; readAt: number } | null>(null);
  const words = said !== null && said.readAt === listReadAt ? said.words : null;

  return (
    <>
      <Button
        className="mt-1"
        disabled={again.isPending}
        onClick={() => {
          setSaid(null);
          onTap();
          again.ask(roughNoteId, {
            onSuccess: onStarted,
            onError: (error) => {
              const outcome = draftAgainOutcome(error);
              if (outcome.kind === "words") setSaid({ words: outcome.words, readAt: listReadAt });
            },
          });
        }}
      >
        Try drafting again
      </Button>
      {words !== null ? (
        <p role="alert" className="mt-1 w-full font-semibold text-stop">
          {words}
        </p>
      ) : null}
    </>
  );
}
