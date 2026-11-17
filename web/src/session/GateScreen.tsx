import { GateFrame, WhoLine } from "./GateFrame";
import { PIN_LOCKED, screenForGate } from "./pin";
import { SetPinScreen } from "./SetPinScreen";
import { UnlockScreen } from "./UnlockScreen";
import type { Session } from "./session";

/** The PIN is locked: nothing to type, someone with the power to reset it has to. */
function PinLockedScreen({ session }: { session: Session }) {
  return (
    <GateFrame heading={`PIN locked, ${session.display_name}`}>
      <WhoLine session={session} reason="Nobody sees a patient while the PIN is locked." />
      <p className="mt-4 text-18 font-semibold">{PIN_LOCKED}</p>
    </GateFrame>
  );
}

/** The screen the session's gate asks for, to show in place of the page (never both). */
export function GateScreen({ session }: { session: Session }) {
  switch (screenForGate(session.gate)) {
    case "set_pin":
      return <SetPinScreen session={session} />;
    case "enter_pin":
    case "idle_locked":
      return <UnlockScreen session={session} />;
    case "pin_locked":
      return <PinLockedScreen session={session} />;
    case null:
      return null;
  }
}
