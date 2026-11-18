import { PinDialog } from "../settings/PinDialog";
import { failureKind, staffFailureWords } from "./failure";
import { useStaffAction, type StaffAction, type StaffRow } from "./staffApi";
import { DONE, resetWords, revokeWords } from "./words";

export interface Acting {
  action: StaffAction;
  row: StaffRow;
  /** The button that was pressed, to give the focus back to. */
  opener: HTMLElement;
}

/**
 * The PIN dialog for revoking someone or resetting their PIN. `acting` stays set after the dialog
 * closes (`open` says whether it is up). A wrong PIN stays here with the tries left, and so does a
 * connection or server failure (with the connection words); a person who is gone or an action no
 * longer allowed closes it and the page looks at its list again (`onStale`).
 */
export function StaffActionDialog({
  acting,
  open,
  onClose,
  onDone,
  onStale,
}: {
  acting: Acting | null;
  open: boolean;
  onClose: () => void;
  onDone: (words: string) => void;
  onStale: () => void;
}) {
  const revoking = acting?.action === "revoke";
  const request = useStaffAction(
    () => ({ id: acting?.row.id ?? "", action: acting?.action ?? "reset" }),
    {
      onSuccess: (row) => {
        onClose();
        onDone(revoking ? DONE.revoked(row) : DONE.reset(row));
      },
      onError: (error) => {
        const kind = failureKind(error);
        if (kind === "gate" || kind === "stale") onClose();
        if (kind === "stale") onStale();
      },
    },
  );

  return (
    <PinDialog
      open={open}
      onCancel={onClose}
      words={
        acting
          ? revoking
            ? revokeWords(acting.row)
            : resetWords(acting.row)
          : { title: "", question: "", confirm: "", busy: "" }
      }
      request={request}
      persona={false}
      safeFirst={revoking}
      failureWords={staffFailureWords}
      onCloseAutoFocus={(event) => {
        // Back to the button that was pressed; if it is gone (a revoked row has none), the row.
        event.preventDefault();
        if (acting?.opener.isConnected) acting.opener.focus();
        else if (acting) document.getElementById(`staff-row-${acting.row.id}`)?.focus();
      }}
    />
  );
}
