import { useQuery } from "@tanstack/react-query";
import { cn } from "../lib/cn";
import { signInOptionsQuery, useSession } from "./session";
import { offeredFrom } from "./signInOptions";

/**
 * "Demo PIN: 135790": the PIN every demo person shares, on its own paper patch so a ruled line
 * never runs through the digits. A tester who comes back hours later has never chosen it, and each
 * wrong try counts toward ending the demo session.
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
    <p
      id={id}
      className={cn(
        "inline-block rounded-control border border-rule-strong bg-sheet px-2 py-0.5 font-note text-ink",
        className,
      )}
    >{`Demo PIN: ${pin}`}</p>
  );
}

/** The demo PIN to show to the signed-in person: only a demo person is shown it, and only while the demo is on. */
export function useDemoPin(): string | null {
  const { data: session } = useSession();
  const persona = session?.kind === "persona";
  const options = useQuery({ ...signInOptionsQuery, enabled: persona });
  return persona ? offeredFrom(options.data).demoPin : null;
}
