import { useRef, type ReactNode, type RefObject } from "react";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "../components/ui/Dialog";
import { WriteProblem } from "./WriteProblem";
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

/** The two buttons: the confirming one first and firm, the way out second (and where the focus starts). */
function Choice({
  yes,
  yesBusy,
  no,
  busy,
  onYes,
  onNo,
  primary,
  safe,
}: {
  yes: string;
  yesBusy: string;
  no: string;
  busy: boolean;
  onYes: () => void;
  onNo: () => void;
  primary: boolean;
  safe: RefObject<HTMLButtonElement | null>;
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
      {/* While the write is under way the way out waits: the other button's "…ing" is the reason. */}
      <button
        type="button"
        ref={safe}
        className="btn"
        aria-disabled={busy || undefined}
        onClick={() => {
          if (!busy) onNo();
        }}
      >
        {no}
      </button>
    </div>
  );
}

/**
 * The panel. It opens with the focus on the safe choice (an Enter held down on the opener must
 * not go on to sign or discard), and can't be dismissed while the write is under way.
 */
function Panel({
  shared,
  title,
  busy,
  safe,
  children,
}: {
  shared: Shared;
  title: string;
  busy: boolean;
  safe: RefObject<HTMLButtonElement | null>;
  children: ReactNode;
}) {
  const hold = (event: Event) => {
    if (busy) event.preventDefault();
  };
  return (
    <DialogContent
      container={shared.container}
      className="note-dialog"
      onOpenAutoFocus={(event) => {
        event.preventDefault();
        safe.current?.focus();
      }}
      onCloseAutoFocus={shared.onCloseAutoFocus}
      onEscapeKeyDown={hold}
      onPointerDownOutside={hold}
      onInteractOutside={hold}
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
  const safe = useRef<HTMLButtonElement>(null);
  const close = (open: boolean) => {
    if (!open && sign.isPending) return;
    if (!open) sign.reset();
    shared.onOpenChange(open);
  };
  return (
    <Dialog open={shared.open} onOpenChange={close}>
      <Panel shared={shared} title={`Sign this ${format} note`} busy={sign.isPending} safe={safe}>
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
          safe={safe}
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
                // With no line to go to, the dialog stays and says what to do.
                if (failure.kind === "incomplete" && failure.lineIds.length > 0) {
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
  const safe = useRef<HTMLButtonElement>(null);
  const close = (open: boolean) => {
    if (!open && discard.isPending) return;
    if (!open) discard.reset();
    shared.onOpenChange(open);
  };
  return (
    <Dialog open={shared.open} onOpenChange={close}>
      <Panel shared={shared} title="Discard this draft?" busy={discard.isPending} safe={safe}>
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
          safe={safe}
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
