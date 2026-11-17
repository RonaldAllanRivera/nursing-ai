import type { Ref } from "react";
import { Icon } from "../components/Icon";
import { PIN_LENGTH } from "./pin";

/** Only the digits of what was typed or pasted, at most six. */
export function digitsOnly(value: string): string {
  return value.replace(/[^0-9]/g, "").slice(0, PIN_LENGTH);
}

interface PinFieldProps {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  /** Why the last try failed, in words; the field is marked invalid and points at it. */
  message?: string | null;
  /** Hidden-from-sight help the field is also described by (the screen's hint). */
  describedBy?: string;
  ref?: Ref<HTMLInputElement>;
  disabled?: boolean;
}

/**
 * The one PIN input every PIN screen uses (the gates, signing, settings, staff): six digits, shown
 * as dots so a passer-by can't read them, a numeric keypad on a phone, and no browser memory of it.
 */
export function PinField({
  id,
  label,
  value,
  onChange,
  message,
  describedBy,
  ref,
  disabled,
}: PinFieldProps) {
  const messageId = `${id}-message`;
  const described = [describedBy, message ? messageId : undefined].filter(Boolean).join(" ");
  return (
    <div>
      <label htmlFor={id} className="block text-18 font-bold">
        {label}
      </label>
      <input
        ref={ref}
        id={id}
        type="password"
        inputMode="numeric"
        autoComplete="off"
        maxLength={PIN_LENGTH}
        value={value}
        disabled={disabled}
        aria-invalid={message ? true : undefined}
        aria-describedby={described || undefined}
        onChange={(event) => {
          onChange(digitsOnly(event.target.value));
        }}
        className="mt-1 block min-h-12 w-full max-w-[14rem] rounded-control border border-rule-strong bg-sheet px-3 font-note text-24 tracking-[0.35em] text-ink"
      />
      {message ? (
        <p id={messageId} role="alert" className="mt-2 flex items-start gap-2 text-stop">
          <Icon name="flag" className="mt-1" />
          <span>{message}</span>
        </p>
      ) : null}
    </div>
  );
}
