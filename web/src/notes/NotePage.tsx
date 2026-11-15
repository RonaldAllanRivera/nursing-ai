import { useQuery } from "@tanstack/react-query";
import { Link, useParams, useSearch } from "@tanstack/react-router";
import { ApiError } from "../api/errors";
import { Skeleton } from "../components/ui/Skeleton";
import { useFacility } from "../facility/useFacility";
import { useSession } from "../session/session";
import { noteQuery } from "./note";
import { TraceView } from "./TraceView";

const BACK_LINK =
  "inline-flex min-h-11 items-center font-semibold text-pen underline underline-offset-4";

/** One note: the trace view once it has loaded, a plain message or placeholders until then. */
export function NotePage() {
  const { noteId } = useParams({ from: "/app/notes/$noteId" });
  const { line } = useSearch({ from: "/app/notes/$noteId" });
  const { data: session } = useSession();
  const facility = useFacility(session?.facility_key ?? null);
  const note = useQuery(noteQuery(noteId));

  // The error screen is only for a page with nothing to show. A failed refetch keeps the data, and
  // the note, its draft and the selected line stay where they are.
  if ((!note.data && note.isError) || (!facility.data && facility.isError)) {
    const missing = note.error instanceof ApiError && note.error.status === 404;
    return (
      <section>
        <Link to="/patients" className={BACK_LINK}>
          Back to the patients
        </Link>
        <p
          role={missing ? undefined : "alert"}
          className={missing ? "mt-2 text-ink-2" : "mt-2 text-stop"}
        >
          {missing
            ? "This note is not on your list. Go back and pick one."
            : "This note did not load. Go back and try again."}
        </p>
      </section>
    );
  }
  if (!note.data || !facility.data) {
    return (
      <section>
        <Link to="/patients" className={BACK_LINK}>
          Back to the patients
        </Link>
        <div aria-busy="true" className="mt-2 grid gap-3">
          <span className="sr-only">Loading the note…</span>
          <Skeleton className="h-16 w-2/3" />
          <div className="grid gap-4 min-[960px]:grid-cols-[5fr_7fr]">
            <Skeleton className="h-64" />
            <Skeleton className="h-96" />
          </div>
        </div>
      </section>
    );
  }

  const { patient } = note.data.note;
  return (
    <section>
      <Link to="/patients/$patientId" params={{ patientId: patient.id }} className={BACK_LINK}>
        {`Back to ${patient.display_name}`}
      </Link>
      <TraceView
        note={note.data.note}
        locale={facility.data.profile.locale}
        clock={facility.data.profile.clock}
        selectedId={line}
      />
    </section>
  );
}
