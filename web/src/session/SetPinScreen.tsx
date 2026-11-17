import { useEffect, useRef, useState } from "react";
import { Button } from "../components/ui/Button";
import { GateFrame, WHO_ID, WhoLine } from "./GateFrame";
import { PIN_SHORT, PINS_DIFFER, isPinTyped, pinProblemMessage } from "./pin";
import { PinField } from "./PinField";
import { useSetPin, type Session } from "./session";

type Problem = { field: "first" | "again"; text: string } | null;

/** A Google user's first sign-in: choose a PIN, typed twice. A mismatch is caught before anything is sent. */
export function SetPinScreen({ session }: { session: Session }) {
  const setPin = useSetPin();
  const [first, setFirst] = useState("");
  const [again, setAgain] = useState("");
  // A problem found here, before anything was sent. The server's own words come from `setPin.error`.
  const [problem, setProblem] = useState<Problem>(null);
  // Once she edits a field the server's last answer no longer applies.
  const [edited, setEdited] = useState(false);
  const firstField = useRef<HTMLInputElement>(null);

  useEffect(() => {
    firstField.current?.focus();
  }, []);

  const serverWords =
    setPin.error !== null && !edited ? pinProblemMessage(setPin.error, false) : null;

  return (
    <GateFrame heading={`Choose a PIN, ${session.display_name}`}>
      <WhoLine session={session} reason="Nobody sees a patient until you choose a PIN." />
      <p id="set-pin-hint" className="mt-3 text-ink-2">
        You will type it after every sign-in and when you sign a note. Use 6 digits that are not one
        digit repeated or a run like 123456.
      </p>
      <form
        className="mt-4 grid gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          if (setPin.pending) return;
          if (!isPinTyped(first)) {
            setProblem({ field: "first", text: PIN_SHORT });
            return;
          }
          if (first !== again) {
            setProblem({ field: "again", text: PINS_DIFFER });
            return;
          }
          setProblem(null);
          setEdited(false);
          void setPin.run(first).then((ok) => {
            if (ok) return;
            // Both are cleared to try again, and the cursor goes to the first one.
            setFirst("");
            setAgain("");
            firstField.current?.focus();
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
            setEdited(true);
          }}
          describedBy={`${WHO_ID} set-pin-hint`}
          message={
            problem?.field === "first" ? problem.text : problem === null ? serverWords : null
          }
          readOnly={setPin.pending}
        />
        <PinField
          id="set-pin-again"
          label="Type it again"
          value={again}
          onChange={(value) => {
            setAgain(value);
            setProblem(null);
            setEdited(true);
          }}
          message={problem?.field === "again" ? problem.text : null}
          readOnly={setPin.pending}
        />
        <div>
          <Button type="submit" variant="primary" disabled={setPin.pending}>
            {setPin.pending ? "Saving…" : "Save PIN"}
          </Button>
        </div>
      </form>
    </GateFrame>
  );
}
