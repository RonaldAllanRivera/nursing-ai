import { useRef } from "react";
import { Button } from "../components/ui/Button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "../components/ui/Dialog";
import { PinField } from "../session/PinField";
import { usePinEntry } from "../session/usePinEntry";

/** The part of `usePinRequest` this dialog reads. */
interface PinRequest {
  run: (pin: string) => Promise<boolean>;
  pending: boolean;
  error: unknown;
  clear: () => void;
}

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
}: {
  open: boolean;
  onCancel: () => void;
  words: Words;
  request: PinRequest;
  persona: boolean;
  /** Where the focus goes when the dialog closes (the form's own button, or a field to fix). */
  onCloseAutoFocus: (event: Event) => void;
}) {
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
        // The PIN field is the first thing to focus in the dialog, so it takes the focus by itself.
        onCloseAutoFocus={onCloseAutoFocus}
        onEscapeKeyDown={hold}
        onPointerDownOutside={hold}
        onInteractOutside={hold}
      >
        <DialogTitle>{words.title}</DialogTitle>
        <DialogDescription>{words.question}</DialogDescription>
        {words.note ? <p className="mt-2 text-ink-2">{words.note}</p> : null}
        <PinForm
          request={request}
          persona={persona}
          confirm={words.confirm}
          busy={words.busy}
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
  confirm,
  busy,
  onCancel,
}: {
  request: PinRequest;
  persona: boolean;
  confirm: string;
  busy: string;
  onCancel: () => void;
}) {
  const field = useRef<HTMLInputElement>(null);
  const entry = usePinEntry(request, persona, field);
  return (
    <form
      noValidate
      onSubmit={entry.onSubmit}

      className="mt-4 grid gap-4"
    >
      <PinField
        ref={field}
        id={FIELD_ID}
        label="Your PIN"
        value={entry.pin}
        onChange={entry.onChange}
        message={entry.message}
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
