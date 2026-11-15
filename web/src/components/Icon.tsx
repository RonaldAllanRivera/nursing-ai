import { cn } from "../lib/cn";

// The mockup's sprite, symbol by symbol. Only the symbols a screen uses are here; add the rest
// (check, pen, neq, flag, fork, you, removed, lock, box, boxcheck, close) with the screen that needs them.
const PATHS = {
  moon: <path d="M20 14.6A8.2 8.2 0 0 1 9.4 4a8.2 8.2 0 1 0 10.6 10.6z" />,
} as const;

export type IconName = keyof typeof PATHS;

/** Decorative: the words next to it carry the meaning. */
export function Icon({ name, className }: { name: IconName; className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden="true"
      className={cn(
        "size-[1.25em] flex-none fill-none stroke-current stroke-2 [stroke-linecap:round] [stroke-linejoin:round]",
        className,
      )}
    >
      {PATHS[name]}
    </svg>
  );
}
