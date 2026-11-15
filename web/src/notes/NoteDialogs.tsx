import type { ReactNode } from "react";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "../components/ui/Dialog";
import { WriteProblem } from "./LineActions";
import { failureOf, useFinishNote } from "./writes";

interface Shared {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Where the dialog is mounted (the trace view's root, so its stylesheet applies). */
  container: HTMLElement | null;
  noteId: string;
  /** Radix gives the focus back to the opener; a dialog that ended its opener can send it elsewhere. */
  onCloseAutoFocus: (event: Event) => void;
}

/** The two buttons: the confirming one first and firm, the way out second. */
function Choice({
  yes,
  yesBusy,
  no,
  busy,
  onYes,
  onNo,
  primary,
}: {
  yes: string;
  yesBusy: string;
  no: string;
  busy: boolean;
  onYes: () => void;
  onNo: () => void;
  primary: boolean;
}) {
  return (
    <div className="actions">
      <button
        type="button"
        className={primary ? "btn btn-primary" : "btn btn-firm"}
        aria-disabled={busy || undefined}
        onClick={() => {
          if (!busy) onYes();
        }}
      >
        {busy ? yesBusy : yes}
      </button>
      <button type="button" className="btn" onClick={onNo}>
        {no}
      </button>
    </div>
  );
}

function Panel({
  shared,
  title,
  children,
}: {
  shared: Shared;
  title: string;
  children: ReactNode;
}) {
  return (
    <DialogContent
      container={shared.container}
      className="note-dialog"
      onCloseAutoFocus={shared.onCloseAutoFocus}
    >
      <DialogTitle>{title}</DialogTitle>
      {children}
    </DialogContent>
  );
}

/** "Sign this FDAR note": who is signing, what is missing, then Sign note. No PIN. */
export function SignDialog({
  format,
  signerName,
  missing,
  onSigned,
  onIncomplete,
  ...shared
}: Shared & {
  /** "FDAR" or "DAR": the facility's word. */
  format: string;
  signerName: string;
  /** Checklist subjects the note lacks. */
  missing: string[];
  onSigned: () => void;
  onIncomplete: (lineIds: string[]) => void;
}) {
  const sign = useFinishNote(shared.noteId, "sign");
  const close = (open: boolean) => {
    if (!open) sign.reset();
    shared.onOpenChange(open);
  };
  return (
    <Dialog open={shared.open} onOpenChange={close}>
      <Panel shared={{ ...shared, onOpenChange: close }} title={`Sign this ${format} note`}>
        <DialogDescription>
          {`You're signing as ${signerName}. After you sign, the note is locked.`}
        </DialogDescription>
        {missing.length > 0 ? (
          <div className="dialog-list">
            <p>
              <b>Not in this note:</b> {`${missing.join(", ")}. You can still sign.`}
            </p>
          </div>
        ) : null}
        {sign.isError ? (
          <WriteProblem
            error={sign.error}
            noteId={shared.noteId}
            onReloaded={() => {
              sign.reset();
            }}
          />
        ) : null}
        <Choice
          primary
          yes="Sign note"
          yesBusy="Signing…"
          no="Cancel"
          busy={sign.isPending}
          onNo={() => {
            close(false);
          }}
          onYes={() => {
            sign.mutate(undefined, {
              onSuccess: () => {
                onSigned();
                close(false);
              },
              onError: (error) => {
                const failure = failureOf(error);
                if (failure.kind === "incomplete") {
                  onIncomplete(failure.lineIds);
                  close(false);
                }
              },
            });
          }}
        />
      </Panel>
    </Dialog>
  );
}

/** "Discard this draft?": it never reaches the record, but the typed note is kept. */
export function DiscardDialog({
  onDiscarded,
  ...shared
}: Shared & {
  onDiscarded: () => void;
}) {
  const discard = useFinishNote(shared.noteId, "discard");
  const close = (open: boolean) => {
    if (!open) discard.reset();
    shared.onOpenChange(open);
  };
  return (
    <Dialog open={shared.open} onOpenChange={close}>
      <Panel shared={{ ...shared, onOpenChange: close }} title="Discard this draft?">
        <DialogDescription>
          It won&apos;t reach the record. Your typed note stays saved.
        </DialogDescription>
        {discard.isError ? (
          <WriteProblem
            error={discard.error}
            noteId={shared.noteId}
            onReloaded={() => {
              discard.reset();
            }}
          />
        ) : null}
        <Choice
          primary={false}
          yes="Discard draft"
          yesBusy="Discarding…"
          no="Keep draft"
          busy={discard.isPending}
          onNo={() => {
            close(false);
          }}
          onYes={() => {
            discard.mutate(undefined, {
              onSuccess: () => {
                onDiscarded();
                close(false);
              },
            });
          }}
        />
      </Panel>
    </Dialog>
  );
}
