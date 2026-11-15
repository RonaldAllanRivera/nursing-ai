import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

// Teach tailwind-merge our tokens (styles/tokens.css): without this `text-14` reads as a colour
// and knocks out `text-ink`, and `rounded-control` does not merge with `rounded-full`.
const twMerge = extendTailwindMerge({
  extend: {
    theme: {
      text: ["12", "14", "16", "18", "21", "24", "36"],
      radius: ["mark", "control", "sheet", "drawer"],
    },
  },
});

/** shadcn/ui's helper: join class names, and let a later Tailwind class win over an earlier one. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
