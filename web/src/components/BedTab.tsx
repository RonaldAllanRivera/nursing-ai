import { cn } from "../lib/cn";

/**
 * The bed tab from the mockup: the bed (or room) word over its label, on the primary ink.
 * `large` is the note page's: 64 px on a wide screen, 52 px on a small one.
 */
export function BedTab({
  word,
  label,
  large = false,
  className,
}: {
  word: string;
  label: string;
  large?: boolean;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "grid min-w-14 flex-none place-items-center rounded-control rounded-bl-[2px] bg-primary px-2 py-1 leading-none text-primary-ink",
        large && "size-13 min-w-0 p-0 min-[960px]:size-16",
        className,
      )}
    >
      <span className="text-12 font-medium opacity-85">{word}</span>
      <span
        className={cn("text-21 font-bold", large && "text-24 tracking-tight min-[960px]:text-36")}
      >
        {label}
      </span>
    </span>
  );
}
