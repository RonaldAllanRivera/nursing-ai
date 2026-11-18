import { useRef, type RefObject } from "react";
import { Button } from "../components/ui/Button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "../components/ui/Dialog";
import { PinField } from "../session/PinField";
import { DemoPinChip, useDemoPin } from "../session/DemoPin";
import { pinProblemMessage } from "../session/pin";
import { usePinEntry, type PinRequest } from "../session/usePinEntry";

/** What the dialog asks and what its buttons say. */
interface Words {
  title: string;
  question: string;
  /** A second line (what else the action does), under the question. */
  note?: string | null;
  confirm: string;
  busy: string;
}

/**
 * "Enter your PIN to ..." for an admin action the server wants proved with the PIN (saving the
 * settings, putting the demo back). The parent owns whether it is open and what happens after:
 * it closes the dialog when the request worked, or failed in a way the form explains. A wrong
 * PIN is the one failure that stays here, with the tries left.
 */
export function PinDialog({
  open,
  onCancel,
  words,
  request,
  persona,
  onCloseAutoFocus,
  safeFirst = false,
  showFailure = false,
}: {
  open: boolean;
  onCancel: () => void;
  words: Words;
  request: PinRequest;
  persona: boolean;
  /** Where the focus goes when the dialog closes (the form's own button, or a field to fix). */
  onCloseAutoFocus: (event: Event) => void;
  /** For a destructive action: the focus starts on Cancel, the safe choice, not on the PIN field. */
  safeFirst?: boolean;
  /**
   * Say a failure that is not a wrong PIN (no connection, a server error) under the field too. For
   * a dialog that stays open on those so the person can try again; the others explain their own.
   */
  showFailure?: boolean;
}) {
  const cancel = useRef<HTMLButtonElement>(null);
  const hold = (event: Event) => {
    if (request.pending) event.preventDefault();
  };
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (next || request.pending) return;
        request.clear();
        onCancel();
      }}
    >
      <DialogContent
        // The PIN field is the first thing to focus in the dialog, so it takes the focus by itself
        // (unless the action is destructive: then Cancel does).
        onOpenAutoFocus={
          safeFirst
            ? (event) => {
                event.preventDefault();
                cancel.current?.focus();
              }
            : undefined
        }
        onCloseAutoFocus={onCloseAutoFocus}
        onEscapeKeyDown={hold}
        onPointerDownOutside={hold}
        onInteractOutside={hold}
      >
        <DialogTitle>{words.title}</DialogTitle>
        <DialogDescription>
          {words.question}
          {/* Inside the description, so a screen reader hears the consequence as the dialog opens. */}
          {words.note ? (
            <>
              {" "}
              <span className="mt-2 block text-ink-2">{words.note}</span>
            </>
          ) : null}
        </DialogDescription>
        <PinForm
          request={request}
          persona={persona}
          showFailure={showFailure}
          confirm={words.confirm}
          busy={words.busy}
          cancelRef={cancel}
          onCancel={() => {
            request.clear();
            onCancel();
          }}
        />
      </DialogContent>
    </Dialog>
  );
}

const FIELD_ID = "action-pin";

/** The field and the two buttons. It is mounted only while the dialog is open, so the typed digits go when it closes. */
function PinForm({
  request,
  persona,
  showFailure,
  confirm,
  busy,
  cancelRef,
  onCancel,
}: {
  request: PinRequest;
  persona: boolean;
  showFailure: boolean;
  confirm: string;
  busy: string;
  cancelRef: RefObject<HTMLButtonElement | null>;
  onCancel: () => void;
}) {
  const field = useRef<HTMLInputElement>(null);
  const entry = usePinEntry(request, persona, field);
  const demoPin = useDemoPin();
  return (
    <form
      noValidate
      onSubmit={entry.onSubmit}

      className="mt-4 grid gap-4"
    >
      {demoPin ? (
        <DemoPinChip pin={demoPin} id="action-demo-pin" className="justify-self-start" />
      ) : null}
      <PinField
        ref={field}
        id={FIELD_ID}
        {...(demoPin ? { describedBy: "action-demo-pin" } : {})}
        label="Your PIN"
        value={entry.pin}
        onChange={entry.onChange}
        message={
          entry.message ??
          (showFailure && request.error ? pinProblemMessage(request.error, persona) : null)
        }
        readOnly={request.pending}
        onKeyDown={entry.onKeyDown}
      />
      <div className="flex flex-wrap gap-3">
        <Button
          type="submit"
          variant="primary"
          aria-disabled={request.pending || undefined}
          onClick={(event) => {
            if (request.pending) event.preventDefault();
          }}
        >
          {request.pending ? busy : confirm}
        </Button>
        <Button
          ref={cancelRef}
          aria-disabled={request.pending || undefined}
          onClick={() => {
            if (!request.pending) onCancel();
          }}
        >
          Cancel
        </Button>
      </div>
    </form>
  );
}
