import { cn } from "../lib/cn";

/** The bed tab from the mockup: the bed (or room) word over its label, on the primary ink. */
export function BedTab({
  word,
  label,
  className,
}: {
  word: string;
  label: string;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "grid min-w-14 flex-none place-items-center rounded-control rounded-bl-[2px] bg-primary px-2 py-1 leading-none text-primary-ink",
        className,
      )}
    >
      <span className="text-12 font-medium opacity-85">{word}</span>
      <span className="text-21 font-bold">{label}</span>
    </span>
  );
}
