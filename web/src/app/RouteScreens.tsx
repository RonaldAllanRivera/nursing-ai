import { Link, useRouter, type ErrorComponentProps } from "@tanstack/react-router";
import { AidLine } from "../components/AidLine";
import { Icon } from "../components/Icon";
import { Button } from "../components/ui/Button";
import { Skeleton } from "../components/ui/Skeleton";

/** What the router shows when a page can't load or doesn't exist. Plain words; never the error itself. */

/** A page that is still loading (the router shows it only after a short wait). */
export function PendingScreen() {
  return (
    <>
      <AidLine />
      <main aria-busy="true" className="mx-auto grid max-w-[1280px] gap-3 px-4 pt-4 sm:px-6">
        <span className="sr-only">Loading…</span>
        <Skeleton className="h-8 w-2/3" />
        <Skeleton className="h-16" />
        <Skeleton className="h-16" />
      </main>
    </>
  );
}

/** A page whose data or code did not load (a restarting server, a short outage). */
export function ErrorScreen({ reset }: ErrorComponentProps) {
  const router = useRouter();
  return (
    <>
      <AidLine />
      <main className="mx-auto max-w-[1280px] px-4 pt-4 sm:px-6">
        <p role="alert" className="flex items-start gap-2 font-semibold text-stop">
          <Icon name="flag" className="mt-1" />
          <span>Something went wrong loading this page.</span>
        </p>
        <p className="mt-2 text-ink-2">Check the connection, then try again.</p>
        <Button
          variant="primary"
          className="mt-4"
          onClick={() => {
            reset();
            void router.invalidate();
          }}
        >
          Try again
        </Button>
      </main>
    </>
  );
}

/** An address that is not a page here (a typo, an old link). */
export function NotFoundScreen() {
  return (
    <>
      <AidLine />
      <main className="mx-auto max-w-[1280px] px-4 pt-4 sm:px-6">
        <p className="text-18 font-bold">There's no page at this address.</p>
        <Link
          to="/"
          className="mt-2 inline-flex min-h-11 items-center font-semibold text-pen underline underline-offset-4"
        >
          Go to the start
        </Link>
      </main>
    </>
  );
}
