import { useState, type KeyboardEvent, type RefObject, type SyntheticEvent } from "react";
import { PIN_NEEDED, asksPinAgain, isPinTyped, pinProblemMessage } from "./pin";

/** The part of `usePinRequest` a PIN dialog reads. */
export interface PinRequest {
  run: (pin: string) => Promise<boolean>;
  pending: boolean;
  error: unknown;
  clear: () => void;
}

/**
 * What a dialog that asks for the PIN in passing (signing, saving settings, resetting the demo)
 * needs around `PinField` (whose input ref the dialog owns, to focus it): the typed digits, the words under the field, and the form's submit.
 *
 * - Fewer than six digits is turned away with `PIN_NEEDED`, nothing sent.
 * - A wrong PIN clears the field and puts the cursor back in it; the PIN is never kept anywhere
 *   but the field, and the field is emptied whether the request worked or not.
 * - Only a wrong PIN speaks through the field: any other refusal (a stale note, a bad setting) is
 *   the dialog's business, so this stays quiet about it.
 * - An Enter that is held down (a key repeat) never submits. A dialog opened by pressing Enter on
 *   its opener lands the focus in the empty PIN field while the key is still down.
 */
export function usePinEntry(
  request: PinRequest,
  persona: boolean,
  field: RefObject<HTMLInputElement | null>,
) {
  const [pin, setPin] = useState("");
  const [short, setShort] = useState(false);
  // What the request had failed with before this form was shown. A dialog the code closed (not
  // the person) leaves its failure in the request, and that failure is about the try before: a
  // form shows only a failure that came after it opened.
  const [before] = useState(request.error);
  const failure = request.error === before ? null : request.error;

  const message = short
    ? PIN_NEEDED
    : asksPinAgain(failure)
      ? pinProblemMessage(failure, persona)
      : null;

  return {
    pin,
    message,
    /** This try's failure, whatever it was (`message` words only a wrong PIN). */
    failure,
    onChange: (value: string) => {
      setPin(value);
      setShort(false);
    },
    onKeyDown: (event: KeyboardEvent<HTMLInputElement>) => {
      if (event.key === "Enter" && event.repeat) event.preventDefault();
    },
    onSubmit: (event: SyntheticEvent) => {
      event.preventDefault();
      if (request.pending) return;
      if (!isPinTyped(pin)) {
        setShort(true);
        field.current?.focus();
        return;
      }
      setShort(false);
      void request.run(pin).then((ok) => {
        setPin("");
        if (!ok) field.current?.focus();
      });
    },
    /** A dialog closed or opened afresh: nothing of the last try is left. */
    reset: () => {
      setPin("");
      setShort(false);
      request.clear();
    },
  };
}
