import { PinDialog } from "../settings/PinDialog";
import { isPinRefusal } from "../session/pin";
import type { StaffAction } from "./StaffRow";
import type { StaffRow } from "./staffApi";
import { useResetPin, useRevoke } from "./staffApi";
import { DONE, resetWords, revokeWords } from "./words";

export interface Acting {
  action: StaffAction;
  row: StaffRow;
  /** The button that was pressed, to give the focus back to. */
  opener: HTMLElement;
}

/**
 * The PIN dialog for revoking someone or resetting their PIN. `acting` stays set after the dialog
 * closes, so the person it was about is still named while it closes. A wrong PIN stays here with the tries
 * left; any other failure closes it and the page says so (`onFailed`).
 */
export function StaffActionDialog({
  acting,
  open,
  onClose,
  onDone,
  onFailed,
}: {
  acting: Acting | null;
  open: boolean;
  onClose: () => void;
  onDone: (words: string) => void;
  onFailed: (error: unknown) => void;
}) {
  const who = () => acting?.row.id ?? "";
  const failed = (error: unknown) => {
    if (isPinRefusal(error)) return;
    onClose();
    onFailed(error);
  };
  const revoke = useRevoke(who, {
    onSuccess: (row) => {
      onClose();
      onDone(DONE.revoked(row));
    },
    onError: failed,
  });
  const reset = useResetPin(who, {
    onSuccess: (row) => {
      onClose();
      onDone(DONE.reset(row));
    },
    onError: failed,
  });

  const shown = acting;
  const revoking = shown?.action === "revoke";
  return (
    <PinDialog
      open={open}
      onCancel={onClose}
      words={
        shown
          ? revoking
            ? revokeWords(shown.row)
            : resetWords(shown.row)
          : { title: "", question: "", confirm: "", busy: "" }
      }
      request={revoking ? revoke : reset}
      persona={false}
      safeFirst={revoking}
      onCloseAutoFocus={(event) => {
        // Back to the button that was pressed; if it is gone (a revoked row has none), the row.
        event.preventDefault();
        const opener = shown?.opener;
        if (opener?.isConnected) opener.focus();
        else if (shown) document.getElementById(`staff-row-${shown.row.id}`)?.focus();
      }}
    />
  );
}
