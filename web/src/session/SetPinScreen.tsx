import { useEffect, useRef, useState } from "react";
import { Button } from "../components/ui/Button";
import { GateFrame, WhoLine } from "./GateFrame";
import { PIN_SHORT, PINS_DIFFER, isPinTyped, pinProblemMessage } from "./pin";
import { PinField } from "./PinField";
import { useSetPin, type Session } from "./session";

type Problem = { field: "first" | "again"; text: string } | null;

/** A Google user's first sign-in: choose a PIN, typed twice. A mismatch is caught before anything is sent. */
export function SetPinScreen({ session }: { session: Session }) {
  const setPin = useSetPin();
  const [first, setFirst] = useState("");
  const [again, setAgain] = useState("");
  const [problem, setProblem] = useState<Problem>(null);
  const firstField = useRef<HTMLInputElement>(null);

  useEffect(() => {
    firstField.current?.focus();
  }, []);

  return (
    <GateFrame heading={`Choose a PIN, ${session.display_name}`}>
      <WhoLine session={session} />
      <p id="set-pin-hint" className="mt-3 text-ink-2">
        You will type it after every sign-in and when you sign a note. Use 6 digits that are not one
        digit repeated or a run like 123456.
      </p>
      <form
        className="mt-4 grid gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          if (setPin.isPending) return;
          if (!isPinTyped(first)) {
            setProblem({ field: "first", text: PIN_SHORT });
            return;
          }
          if (first !== again) {
            setProblem({ field: "again", text: PINS_DIFFER });
            return;
          }
          setProblem(null);
          setPin.mutate(first, {
            onError: (error) => {
              // The server's words (a weak PIN) go on the first field; both are cleared to try again.
              setProblem({ field: "first", text: pinProblemMessage(error, false) });
              setFirst("");
              setAgain("");
              firstField.current?.focus();
            },
          });
        }}
      >
        <PinField
          ref={firstField}
          id="set-pin-first"
          label="New PIN"
          value={first}
          onChange={(value) => {
            setFirst(value);
            setProblem(null);
          }}
          describedBy="set-pin-hint"
          message={problem?.field === "first" ? problem.text : null}
        />
        <PinField
          id="set-pin-again"
          label="Type it again"
          value={again}
          onChange={(value) => {
            setAgain(value);
            setProblem(null);
          }}
          message={problem?.field === "again" ? problem.text : null}
        />
        <div>
          <Button type="submit" variant="primary" disabled={setPin.isPending}>
            {setPin.isPending ? "Saving…" : "Save PIN"}
          </Button>
        </div>
      </form>
    </GateFrame>
  );
}
