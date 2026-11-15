import type { ComponentProps } from "react";
import { cn } from "../../lib/cn";

type Variant = "primary" | "quiet";

const VARIANTS: Record<Variant, string> = {
  primary: "border-transparent bg-primary text-primary-ink hover:opacity-90",
  quiet: "border-rule-strong bg-transparent text-ink hover:bg-sunk",
};

/** A copied-in shadcn-style button, drawn with our tokens. 44 px tall at least (tap target). */
export function Button({
  variant = "quiet",
  className,
  type = "button",
  ...props
}: ComponentProps<"button"> & { variant?: Variant }) {
  return (
    <button
      type={type}
      className={cn(
        "inline-flex min-h-11 cursor-pointer items-center justify-center gap-2 rounded-full border px-4 font-ui font-semibold disabled:cursor-not-allowed disabled:opacity-60",
        VARIANTS[variant],
        className,
      )}
      {...props}
    />
  );
}
