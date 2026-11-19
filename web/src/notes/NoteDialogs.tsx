import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { DemoPinChip, useDemoPin } from "../session/DemoPin";
import { asksPinAgain } from "../session/pin";
import { PinField } from "../session/PinField";
import { explainDemoEnd, useSession } from "../session/session";
import { usePinEntry } from "../session/usePinEntry";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "../components/ui/Dialog";
import { WriteProblem } from "./WriteProblem";
import { failureOf, useDiscardNote, lineWriteKey, useNoteWriting, useSignNote } from "./writes";

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
  submit = false,
  hold,
}: {
  yes: string;
  yesBusy: string;
  no: string;
  busy: boolean;
  /** Not needed when the first button submits the form around it. */
  onYes?: () => void;
  onNo: () => void;
  primary: boolean;
  safe?: RefObject<HTMLButtonElement | null>;
  submit?: boolean;
  /** The id of the line that says why the first button waits: it is unavailable until that clears. */
  hold?: string | undefined;
}) {
  return (
    <div className="actions">
      <button
        type={submit ? "submit" : "button"}
        className={primary ? "btn btn-primary" : "btn btn-firm"}
        aria-disabled={busy || hold !== undefined || undefined}
        aria-describedby={hold}
        onClick={() => {
          if (!busy && !submit) onYes?.();
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
 * The panel. It opens with the focus where an Enter held down on the opener can't sign or
 * discard (the safe choice, or the empty PIN field), and can't be dismissed while the write is
 * under way.
 */
function Panel({
  shared,
  title,
  busy,
  focus,
  children,
}: {
  shared: Shared;
  title: string;
  busy: boolean;
  /** What takes the focus when the dialog opens: the safe choice, or an empty PIN field. */
  focus: RefObject<HTMLElement | null>;
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
        focus.current?.focus();
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

const CHANGE_SAVING =
  "Your last change to this note is still being saved. Sign note will work in a moment; your PIN stays here.";
const CHANGE_LOST =
  "Your last change to this note was not saved. Close this and check the note before signing.";

/** "Sign this FDAR note": who is signing, what is missing, her PIN, then Sign note. */
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
  const queryClient = useQueryClient();
  const { data: session } = useSession();
  const persona = session?.kind === "persona";
  const demoPin = useDemoPin();
  const sign = useSignNote(shared.noteId, {
    onSuccess: () => {
      onSigned();
      done();
    },
    onError: (error, previous) => {
      if (persona) explainDemoEnd(queryClient, error, previous);
      const failure = failureOf(error);
      // With no line to go to, the dialog stays and says what to do.
      if (failure.kind === "incomplete" && failure.lineIds.length > 0) {
        onIncomplete(failure.lineIds);
        done();
      }
    },
  });
  const field = useRef<HTMLInputElement>(null);
  const { writing, writingNow } = useNoteWriting(shared.noteId);
  // A line change that failed while this dialog was open: she must look at the note before signing.
  const [lostChange, setLostChange] = useState(false);
  const lostRef = useRef(false);
  const [said, setSaid] = useState("");
  const entry = usePinEntry(
    sign,
    persona,
    field,
    () => lostRef.current || writingNow(),
    () => {
      // Said again on every held try: a screen reader hears it even though nothing on screen moved.
      setSaid("");
      window.setTimeout(() => {
        setSaid(lostRef.current ? CHANGE_LOST : CHANGE_SAVING);
      }, 50);
    },
  );
  const waitingForWrite = (writing && !sign.pending) || lostChange;
  const wasHeld = useRef(false);
  useEffect(() => {
    if (!shared.open) return;
    return queryClient.getMutationCache().subscribe((event) => {
      const key = event.mutation?.options.mutationKey;
      if (
        event.type === "updated" &&
        event.action.type === "error" &&
        key?.[0] === lineWriteKey(shared.noteId)[0] &&
        key[1] === shared.noteId
      ) {
        lostRef.current = true;
        setLostChange(true);
        setSaid(CHANGE_LOST);
      }
    });
  }, [shared.open, shared.noteId, queryClient]);
  useEffect(() => {
    if (wasHeld.current && !waitingForWrite) setSaid("You can sign now.");
    wasHeld.current = waitingForWrite;
  }, [waitingForWrite]);
  const describedBy =
    [demoPin ? "sign-demo-pin" : "", waitingForWrite ? "sign-waiting" : ""]
      .filter(Boolean)
      .join(" ") || undefined;
  /** Closes the dialog with nothing of the last try left in it (the typed PIN, the words under it). */
  function done() {
    lostRef.current = false;
    setLostChange(false);
    setSaid("");
    entry.reset();
    shared.onOpenChange(false);
  }
  const close = (open: boolean) => {
    if (!open && sign.pending) return;
    if (!open) done();
    else shared.onOpenChange(open);
  };
  return (
    <Dialog open={shared.open} onOpenChange={close}>
      <Panel shared={shared} title={`Sign this ${format} note`} busy={sign.pending} focus={field}>
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
        <form noValidate onSubmit={entry.onSubmit}>
          {/* The same room between the hint and the field as every other PIN prompt: the hint
              reads as a note above, not as part of the field's label. */}
          <div className="mt-4 grid gap-4">
            {demoPin ? (
              <DemoPinChip pin={demoPin} id="sign-demo-pin" className="justify-self-start" />
            ) : null}
            <PinField
              ref={field}
              id="sign-pin"
              {...(describedBy ? { describedBy } : {})}
              label="Your PIN"
              value={entry.pin}
              onChange={entry.onChange}
              message={entry.message}
              readOnly={sign.pending}
              onKeyDown={entry.onKeyDown}
            />
          </div>
          {waitingForWrite ? (
            <p id="sign-waiting" className="mt-3 text-14">
              {lostChange ? CHANGE_LOST : CHANGE_SAVING}
            </p>
          ) : null}
          {/* Always here, so what it says is announced as a change, not as a new node. */}
          <p role="status" className="sr-only" id="sign-live">
            {said}
          </p>
          {sign.error !== null && !asksPinAgain(sign.error) ? (
            <WriteProblem
              error={sign.error}
              noteId={shared.noteId}
              onReloaded={() => {
                sign.clear();
              }}
            />
          ) : null}
          <Choice
            primary
            submit
            yes="Sign note"
            yesBusy="Signing…"
            no="Cancel"
            busy={sign.pending}
            hold={waitingForWrite ? "sign-waiting" : undefined}
            onNo={() => {
              close(false);
            }}
          />
        </form>
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
  const discard = useDiscardNote(shared.noteId);
  const safe = useRef<HTMLButtonElement>(null);
  const close = (open: boolean) => {
    if (!open && discard.isPending) return;
    if (!open) discard.reset();
    shared.onOpenChange(open);
  };
  return (
    <Dialog open={shared.open} onOpenChange={close}>
      <Panel shared={shared} title="Discard this draft?" busy={discard.isPending} focus={safe}>
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
