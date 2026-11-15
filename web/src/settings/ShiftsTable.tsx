import { useRef, type Ref } from "react";
import { useFieldArray, useWatch, type UseFormReturn } from "react-hook-form";
import { Icon } from "../components/Icon";
import { Button } from "../components/ui/Button";
import { cn } from "../lib/cn";
import { Field, INPUT, RadioGroup } from "./fields";
import type { FormValues } from "./form";

const INK_EDGE = {
  blue: "border-l-shift-blue",
  black: "border-l-shift-black",
  red: "border-l-shift-red",
} as const;

const INKS = [
  { value: "blue", label: "Blue", ink: "blue" },
  { value: "black", label: "Black", ink: "black" },
  { value: "red", label: "Red", ink: "red" },
] as const;

/** The form's name for one part of one shift. */
function path<P extends "code" | "label" | "starts_local" | "ends_local" | "ink">(
  index: number,
  part: P,
) {
  return `shifts.${String(index)}.${part}` as `shifts.${number}.${P}`;
}

/** What is wrong with the table as a whole: the client's check first, then the server's words. */
export function TableProblems({
  problems,
  ref,
}: {
  problems: readonly string[];
  ref: Ref<HTMLDivElement>;
}) {
  if (problems.length === 0) return null;
  return (
    <div
      id="shift-problems"
      ref={ref}
      tabIndex={-1}
      className="mt-2 rounded-control border border-review bg-review-tint p-3 text-review"
    >
      <p className="flex items-center gap-2 font-semibold">
        <Icon name="flag" />
        Fix the shifts before you save
      </p>
      <ul className="mt-1 list-disc pl-8">
        {problems.map((problem, at) => (
          <li key={`${String(at)}-${problem}`}>{problem}</li>
        ))}
      </ul>
    </div>
  );
}

/**
 * The shifts, one small card each (it never scrolls sideways at 375 px). Each card has the
 * shift's ink down its edge, and the ink is also a choice with its word.
 */
export function ShiftsTable({
  form,
  problems,
  problemsRef,
}: {
  form: UseFormReturn<FormValues>;
  problems: readonly string[];
  problemsRef: Ref<HTMLDivElement>;
}) {
  const { register, control, formState } = form;
  const { fields, append, remove } = useFieldArray({ control, name: "shifts" });
  const shifts = useWatch({ control, name: "shifts" });
  const add = useRef<HTMLButtonElement>(null);
  const errorsOf = (index: number) => formState.errors.shifts?.[index];

  return (
    <fieldset
      aria-describedby={problems.length > 0 ? "shift-problems" : undefined}
      className="m-0 min-w-0 border-0 p-0"
    >
      <legend className="mb-1 text-18 font-bold">Shifts</legend>
      <p className="text-ink-2">
        Together the shifts cover all 24 hours. A shift can end after midnight.
      </p>
      <TableProblems problems={problems} ref={problemsRef} />
      <ul className="m-0 mt-3 grid list-none gap-3 p-0">
        {fields.map((row, index) => {
          const ink = shifts[index]?.ink ?? "blue";
          const errors = errorsOf(index);
          const code = shifts[index]?.code.trim() ?? "";
          const at = (part: string) => `shift-${String(index)}-${part}`;
          return (
            <li key={row.id}>
              <fieldset
                className={cn(
                  "m-0 min-w-0 rounded-control border border-rule border-l-[length:var(--stripe)] bg-paper p-3",
                  INK_EDGE[ink],
                )}
              >
                <legend className="px-1 font-semibold">Shift {index + 1}</legend>
                <div className="grid grid-cols-2 gap-3 md:grid-cols-[7rem_minmax(0,1fr)_9rem_9rem]">
                  <Field id={at("code")} label="Code" error={errors?.code?.message}>
                    {(props) => (
                      <input
                        type="text"
                        autoComplete="off"
                        className={INPUT}
                        {...props}
                        {...register(path(index, "code"))}
                      />
                    )}
                  </Field>
                  <Field id={at("label")} label="Label" error={errors?.label?.message}>
                    {(props) => (
                      <input
                        type="text"
                        autoComplete="off"
                        className={INPUT}
                        {...props}
                        {...register(path(index, "label"))}
                      />
                    )}
                  </Field>
                  <Field id={at("starts")} label="Starts" error={errors?.starts_local?.message}>
                    {(props) => (
                      <input
                        type="time"
                        className={INPUT}
                        {...props}
                        {...register(path(index, "starts_local"))}
                      />
                    )}
                  </Field>
                  <Field id={at("ends")} label="Ends" error={errors?.ends_local?.message}>
                    {(props) => (
                      <input
                        type="time"
                        className={INPUT}
                        {...props}
                        {...register(path(index, "ends_local"))}
                      />
                    )}
                  </Field>
                </div>
                <div className="mt-3 flex flex-wrap items-end justify-between gap-3">
                  <RadioGroup
                    id={at("ink")}
                    legend="Ink"
                    name={path(index, "ink")}
                    choices={INKS}
                    register={register}
                    error={errors?.ink?.message}
                  />
                  <Button
                    onClick={() => {
                      remove(index);
                      add.current?.focus();
                    }}
                    aria-label={
                      code === "" ? `Remove shift ${String(index + 1)}` : `Remove shift ${code}`
                    }
                  >
                    Remove
                  </Button>
                </div>
              </fieldset>
            </li>
          );
        })}
      </ul>
      <Button
        ref={add}
        className="mt-3"
        onClick={() => {
          append({ code: "", label: "", starts_local: "", ends_local: "", ink: "blue" });
        }}
      >
        Add a shift
      </Button>
    </fieldset>
  );
}
