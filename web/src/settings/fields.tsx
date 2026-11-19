import type { ReactNode } from "react";
import type { Path, UseFormRegister } from "react-hook-form";
import { Icon } from "../components/Icon";
import { cn } from "../lib/cn";
import type { FormValues } from "./form";

/** One input's look. The red border backs up the message under it, never replaces it. */
export const INPUT =
  "min-h-11 w-full rounded-control border border-rule-strong bg-sheet px-3 text-ink aria-invalid:border-2 aria-invalid:border-stop";

export const LABEL = "mb-1 block text-14 font-semibold text-ink-2";

/** A field's problem: icon, words and colour. It is the input's description (`aria-describedby`). */
export function FieldError({ id, message }: { id: string; message: string | undefined }) {
  if (!message) return null;
  return (
    <p id={id} className="mt-1 flex items-start gap-2 text-14 text-stop">
      <Icon name="flag" className="mt-0.5 flex-none" />
      <span>{message}</span>
    </p>
  );
}

/**
 * A label, an input and the input's problem. The input gets `id`, `aria-invalid` and
 * `aria-describedby` through the render function.
 */
export function Field({
  id,
  label,
  error,
  hint,
  className,
  children,
}: {
  id: string;
  label: string;
  error: string | undefined;
  /** What the field does, under it; the input is described by it too. */
  hint?: string;
  className?: string;
  children: (props: {
    id: string;
    "aria-invalid": true | undefined;
    "aria-describedby": string | undefined;
  }) => ReactNode;
}) {
  const errorId = `${id}-error`;
  const hintId = `${id}-hint`;
  const described = [hint ? hintId : null, error ? errorId : null].filter(Boolean).join(" ");
  return (
    <div className={className}>
      <label htmlFor={id} className={LABEL}>
        {label}
      </label>
      {children({
        id,
        "aria-invalid": error ? true : undefined,
        "aria-describedby": described || undefined,
      })}
      {hint ? (
        <p id={hintId} className="mt-1 text-14 text-ink-2">
          {hint}
        </p>
      ) : null}
      <FieldError id={errorId} message={error} />
    </div>
  );
}

const SWATCH = {
  blue: "bg-shift-blue",
  black: "bg-shift-black",
  red: "bg-shift-red",
} as const;

export interface Choice {
  value: string;
  label: string;
  /** A shift ink: drawn as a swatch beside its word. */
  ink?: keyof typeof SWATCH;
}

/** A group of radio buttons under a legend. Each choice is a tap-sized pill with its word. */
export function RadioGroup({
  id,
  legend,
  name,
  choices,
  register,
  error,
  className,
}: {
  id: string;
  legend: string;
  name: Path<FormValues>;
  choices: readonly Choice[];
  register: UseFormRegister<FormValues>;
  error: string | undefined;
  className?: string;
}) {
  const errorId = `${id}-error`;
  return (
    <fieldset
      aria-describedby={error ? errorId : undefined}
      data-invalid={error ? "" : undefined}
      className={cn("m-0 min-w-0 border-0 p-0", className)}
    >
      <legend className={cn(LABEL, "p-0")}>{legend}</legend>
      <div className="flex flex-wrap gap-2">
        {choices.map((choice) => (
          <label
            key={choice.value}
            className="inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-control border border-rule-strong bg-sheet px-3 has-checked:border-pen has-checked:bg-pen-tint has-focus-visible:outline-3 has-focus-visible:outline-offset-2 has-focus-visible:outline-pen"
          >
            <input
              type="radio"
              value={choice.value}
              className="size-4 accent-[var(--pen)]"
              {...register(name)}
            />
            {choice.ink ? (
              <span
                aria-hidden="true"
                className={cn("size-4 flex-none rounded-full", SWATCH[choice.ink])}
              />
            ) : null}
            <span>{choice.label}</span>
          </label>
        ))}
      </div>
      <FieldError id={errorId} message={error} />
    </fieldset>
  );
}
