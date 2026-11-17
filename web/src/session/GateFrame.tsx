import type { ReactNode } from "react";
import { GATE_ATTRIBUTE } from "../app/gateFocus";
import { Icon } from "../components/Icon";
import { roleLabel } from "./personas";
import type { Session } from "./session";

/** The ids a gate screen's PIN field is described by, so it is not announced as a bare "secure edit text". */
export const WHO_ID = "gate-who";
export const IDLE_ID = "gate-idle";

/** The paper every gate screen is written on: a lock, then a heading that names whose session it is. */
export function GateFrame({ heading, children }: { heading: string; children: ReactNode }) {
  return (
    <section
      aria-labelledby="gate-heading"
      {...{ [GATE_ATTRIBUTE]: "" }}
      className="mx-auto mt-4 max-w-md rounded-sheet border border-rule bg-sheet p-4 shadow-(--lift) sm:p-6"
    >
      <h1 id="gate-heading" className="flex items-start gap-3 text-24 leading-tight font-bold">
        <Icon name="lock" className="mt-1 flex-none" />
        <span>{heading}</span>
      </h1>
      {children}
    </section>
  );
}

/** Who is signed in, in words, under every gate heading. */
export function WhoLine({
  session,
  reason = "Nobody sees a patient until the PIN is entered.",
}: {
  session: Session;
  reason?: string;
}) {
  return (
    <p id={WHO_ID} className="mt-2 text-ink-2">
      {roleLabel(session.role)}. {reason}
    </p>
  );
}
