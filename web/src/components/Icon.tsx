import { cn } from "../lib/cn";

// The mockup's sprite, symbol by symbol. Only the symbols a screen uses are here; add the rest
// (check, neq, fork, lock, boxcheck, close) with the screen that needs them.
const PATHS = {
  pen: (
    <>
      <path d="M4 20l4.5-1 10.2-10.2a2.1 2.1 0 0 0-3-3L5.5 15.5 4 20z" />
      <path d="M14 7.2l2.8 2.8" />
    </>
  ),
  flag: (
    <>
      <path d="M5.5 21V4" />
      <path d="M5.5 4.5h11.5l-2.2 4.25 2.2 4.25H5.5" />
    </>
  ),
  you: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M8 12.4l2.8 2.8L16.2 9.8" />
    </>
  ),
  removed: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M8 12h8" />
    </>
  ),
  box: <rect x="4" y="4" width="16" height="16" rx="3" />,
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
