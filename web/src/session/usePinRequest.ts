import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

/**
 * A request that carries a PIN (set, unlock, and later signing and staff actions). TanStack keeps
 * a mutation's variables in its cache for minutes, and a PIN may live only in the form field and
 * the one request that sends it. So this runs the request as a mutation that is thrown away as
 * soon as it settles (`gcTime: 0`, then `reset()`), and keeps only the failure it was answered
 * with (a problem, never the PIN) in this component's state.
 *
 * `send` makes the request. `onSuccess` gets its answer; `onError` gets the failure and the one
 * before it (a demo person's fifth wrong PIN is told from an expired session by that).
 * Use `run(pin)` from the form's submit, `pending` for a read-only field and a busy button, and
 * `error` for the words (`pinProblemMessage`); `clear()` forgets the last failure (a dialog closing).
 *
 * `options.scope` puts the request in a TanStack scope: requests that share one run one after the
 * other (the writes to one note), and `send` reads whatever it needs (a version tag) when its turn
 * comes. `options.onMutate` runs just before, once the request is made.
 */
export function usePinRequest<Answer>(
  send: (pin: string) => Promise<Answer>,
  handlers: {
    onSuccess: (answer: Answer) => void | Promise<void>;
    onError?: (error: unknown, previous: unknown) => void;
  },
  options: { scope?: string; onMutate?: () => unknown } = {},
) {
  const mutation = useMutation({
    mutationFn: send,
    gcTime: 0,
    // A PIN is sent once: not again by itself, not even for a waking database.
    retry: false,
    ...(options.scope ? { scope: { id: options.scope } } : {}),
    ...(options.onMutate ? { onMutate: options.onMutate } : {}),
  });
  const [error, setError] = useState<unknown>(null);
  const [pending, setPending] = useState(false);

  /** Resolves `true` when the answer was a success, `false` when it was a failure (shown through `error`). */
  const run = async (pin: string): Promise<boolean> => {
    setPending(true);
    // The last try's words are about the last try: a screen reader must not hear them again.
    setError(null);
    try {
      const answer = await mutation.mutateAsync(pin);
      await handlers.onSuccess(answer);
      return true;
    } catch (failure) {
      setError(failure);
      handlers.onError?.(failure, error);
      return false;
    } finally {
      setPending(false);
      // Drops the variables (the PIN) from the mutation cache now rather than minutes from now.
      mutation.reset();
    }
  };

  const clear = () => {
    setError(null);
  };

  return { run, pending, error, clear };
}
