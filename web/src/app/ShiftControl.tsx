import { useEffect, useRef, useState } from "react";
import { ApiError } from "../api/errors";
import type { components } from "../api/schema";
import { useFacility } from "../facility/useFacility";
import { cn } from "../lib/cn";
import { formatShiftRange } from "../region/format";
import { useChangeShift } from "../session/session";

type ShiftRef = components["schemas"]["ShiftRef"];
type Ink = components["schemas"]["ShiftInk"];

// The shift's ink runs down the edge of its tab, as a paper chart's does. Never text colour.
const INK_EDGE: Record<Ink, string> = {
  blue: "border-l-shift-blue",
  black: "border-l-shift-black",
  red: "border-l-shift-red",
};

/**
 * "Shift 10-6 · change" and, when opened, the facility's other shifts in a row of their own
 * under the header (not floating, so it can never run off a narrow screen).
 */
export function ShiftControl({ shift, facilityKey }: { shift: ShiftRef; facilityKey: string }) {
  const { data: facility, isError: facilityFailed } = useFacility(facilityKey);
  const change = useChangeShift();
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!panel.current?.contains(target) && !trigger.current?.contains(target)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        trigger.current?.focus();
      }
    };
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", close);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  const ink = facility?.profile.shifts.find((s) => s.code === shift.code)?.ink;
  const choose = (startsAt: string) => {
    change.mutate(startsAt, {
      onSuccess: () => {
        setOpen(false);
        trigger.current?.focus();
      },
    });
  };

  return (
    <>
      <span className="inline-flex items-center gap-2">
        <span
          className={cn(
            "rounded-control border border-rule border-l-[length:var(--stripe)] bg-sheet px-2 py-0.5 font-semibold",
            ink ? INK_EDGE[ink] : "border-l-rule-strong",
          )}
        >
          Shift {shift.label}
        </span>
        <span aria-hidden="true">·</span>
        <button
          ref={trigger}
          type="button"
          aria-label="Change shift"
          aria-expanded={open}
          aria-controls="shift-choices"
          onClick={() => {
            change.reset();
            setOpen((was) => !was);
          }}
          className="min-h-11 cursor-pointer px-2 font-semibold text-pen underline underline-offset-4"
        >
          change
        </button>
      </span>
      {open && (
        <div
          id="shift-choices"
          ref={panel}
          role="group"
          aria-label="Shifts you can work"
          className="order-last basis-full rounded-sheet border border-rule bg-sheet p-2 shadow-(--lift)"
        >
          {facilityFailed ? (
            <p role="alert" className="px-2 py-1 text-14 text-stop">
              The shifts did not load. Close this and try again.
            </p>
          ) : facility ? (
            <ul className="grid gap-1 sm:grid-cols-3">
              {facility.shift_choices.map((choice) => {
                const current = Date.parse(choice.starts_at) === Date.parse(shift.starts_at);
                return (
                  <li key={choice.starts_at}>
                    <button
                      type="button"
                      aria-pressed={current}
                      disabled={change.isPending}
                      onClick={() => {
                        choose(choice.starts_at);
                      }}
                      className={cn(
                        "flex min-h-11 w-full cursor-pointer flex-col items-start rounded-control border px-3 py-1 text-left",
                        current ? "border-pen bg-pen-tint" : "border-transparent hover:bg-sunk",
                      )}
                    >
                      <span className="font-semibold">{choice.label}</span>{" "}
                      <span className="text-14 text-ink-2">
                        {formatShiftRange(choice, {
                          locale: facility.profile.locale,
                          clock: facility.profile.clock,
                        })}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="px-2 py-1 text-14 text-ink-2">Loading the shifts…</p>
          )}
          {change.error ? (
            <p role="alert" className="px-2 pt-2 text-14 text-stop">
              {change.error instanceof ApiError && change.error.status === 422
                ? "That shift is not available here. Choose one from the list."
                : "The shift did not change. Try again."}
            </p>
          ) : null}
        </div>
      )}
    </>
  );
}
