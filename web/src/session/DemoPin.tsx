import { useQuery } from "@tanstack/react-query";
import { cn } from "../lib/cn";
import { signInOptionsQuery, useSession } from "./session";
import { offeredFrom } from "./signInOptions";

/**
 * "Demo PIN: 135790": the PIN every demo person shares. A tester who comes back hours later has
 * never chosen it, and each wrong try counts toward ending the demo session. It is a hint, written
 * like one: plain words with the digits in the note font, and no border or box, so it never looks
 * like the PIN field under it already filled in. Its paper is the sheet's, so a ruled line never
 * runs through it. PIN fields point at it by `id` (`describedBy`).
 */
export function DemoPinChip({
  pin,
  id,
  className,
}: {
  pin: string;
  id?: string;
  className?: string;
}) {
  return (
    <p id={id} className={cn("w-fit bg-sheet text-ink-2", className)}>
      Demo PIN: <span className="font-note text-18 font-bold tracking-wider text-ink">{pin}</span>
    </p>
  );
}

/** The demo PIN to show to the signed-in person: only a demo person is shown it, and only while the demo is on. */
export function useDemoPin(): string | null {
  const { data: session } = useSession();
  const persona = session?.kind === "persona";
  const options = useQuery({ ...signInOptionsQuery, enabled: persona });
  return persona ? offeredFrom(options.data).demoPin : null;
}
