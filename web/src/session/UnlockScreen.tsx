import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Button } from "../components/ui/Button";
import { GateFrame, WhoLine } from "./GateFrame";
import { PIN_SHORT, idleLockWords, isPinTyped, pinProblemMessage } from "./pin";
import { PinField } from "./PinField";
import { signInOptionsQuery, useUnlock, type Session } from "./session";
import { offeredFrom } from "./signInOptions";

/** Enter the PIN after signing in, or after the idle lock. A demo person is shown the demo PIN. */
export function UnlockScreen({ session }: { session: Session }) {
  const persona = session.kind === "persona";
  const unlock = useUnlock(persona);
  const options = useQuery({ ...signInOptionsQuery, enabled: persona });
  const demoPin = persona ? offeredFrom(options.data).demoPin : null;
  const [pin, setPin] = useState("");
  const [short, setShort] = useState(false);
  const field = useRef<HTMLInputElement>(null);

  // The page was replaced: the cursor goes to the one thing to do.
  useEffect(() => {
    field.current?.focus();
  }, []);

  const message = short
    ? PIN_SHORT
    : unlock.isError
      ? pinProblemMessage(unlock.error, persona)
      : null;
  const idle = session.gate === "idle_locked";

  return (
    <GateFrame heading={`Enter your PIN, ${session.display_name}`}>
      <WhoLine session={session} />
      {idle ? <p className="mt-1 text-ink-2">{idleLockWords(session.idle_lock_seconds)}</p> : null}
      {demoPin ? (
        <p className="mt-3 inline-block rounded-control border border-rule-strong bg-sheet px-2 py-0.5 font-note text-ink">{`Demo PIN: ${demoPin}`}</p>
      ) : null}
      <form
        className="mt-4 grid gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          if (unlock.isPending) return;
          if (!isPinTyped(pin)) {
            setShort(true);
            return;
          }
          setShort(false);
          unlock.mutate(pin, {
            onError: () => {
              // A wrong PIN is gone from the field at once, and the cursor is back in it.
              setPin("");
              field.current?.focus();
            },
          });
        }}
      >
        <PinField
          ref={field}
          id="unlock-pin"
          label="PIN"
          value={pin}
          onChange={(value) => {
            setPin(value);
            setShort(false);
          }}
          message={message}
        />
        <div>
          <Button type="submit" variant="primary" disabled={unlock.isPending}>
            {unlock.isPending ? "Checking…" : "Unlock"}
          </Button>
        </div>
      </form>
    </GateFrame>
  );
}
