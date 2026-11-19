import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";
import { ApiError } from "../api/errors";
import { BedTab } from "../components/BedTab";
import { SyntheticTag } from "../components/SyntheticTag";
import { Skeleton } from "../components/ui/Skeleton";
import { useFacility } from "../facility/useFacility";
import { RoughNoteForm } from "../notes/RoughNoteForm";
import { ShiftNotes } from "../notes/ShiftNotes";
import { formatShiftRange } from "../region/format";
import { words } from "../region/words";
import { useSession } from "../session/session";
import { patientQuery } from "./patients";

const BACK_LINK =
  "inline-flex min-h-11 items-center font-semibold text-pen underline underline-offset-4";

/** One patient on this shift: who, which shift, the notes so far, and the box to write the next one. */
export function PatientPage() {
  const { patientId } = useParams({ from: "/app/patients/$patientId" });
  const { data: session } = useSession();
  const facility = useFacility(session?.facility_key ?? null);
  const patient = useQuery(patientQuery(patientId));

  const back = (
    <Link to="/patients" className={BACK_LINK}>
      Back to the patients
    </Link>
  );

  // The error page is only for a page that has nothing to show. A failed refetch keeps the data,
  // and the form with the nurse's text stays where it is.
  if ((!patient.data && patient.isError) || (!facility.data && facility.isError)) {
    const missing = patient.error instanceof ApiError && patient.error.status === 404;
    return (
      <section>
        {back}
        <p
          role={missing ? undefined : "alert"}
          className={missing ? "mt-2 text-ink-2" : "mt-2 text-stop"}
        >
          {missing
            ? "This patient is not on your list. Go back and pick one."
            : "This patient did not load. Go back and try again."}
        </p>
      </section>
    );
  }
  if (!patient.data || !facility.data) {
    return (
      <section>
        {back}
        <div aria-busy="true" className="mt-2 grid gap-3">
          <span className="sr-only">Loading the patient…</span>
          <Skeleton className="h-16 w-2/3" />
          <Skeleton className="h-8 w-1/2" />
          <Skeleton className="h-64" />
        </div>
      </section>
    );
  }

  const { summary, shift, notes } = patient.data;
  const { locale, clock } = facility.data.profile;
  const w = words(locale);

  return (
    <section>
      {back}
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-2">
        <BedTab word={w.bed} label={summary.bed_label} />
        <div className="min-w-0">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h1 className="text-24 leading-tight font-bold">{summary.display_name}</h1>
            <SyntheticTag />
          </div>
          <p className="text-ink-2">{`${String(summary.age)} ${summary.sex}, ${summary.ward}`}</p>
        </div>
      </div>
      <p className="mt-3 text-ink-2">
        <span className="font-semibold text-ink">Shift {shift.label}</span>
        {" · "}
        {formatShiftRange(shift, { locale, clock })}
      </p>

      <div className="mt-4 grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="lg:order-2">
          <ShiftNotes
            patientId={patientId}
            notes={notes}
            listReadAt={patient.dataUpdatedAt}
            timeZone={shift.timezone}
            locale={locale}
            clock={clock}
          />
        </div>
        <div className="lg:order-1">
          <RoughNoteForm key={patientId} patientId={patientId} demoNote={patient.data.demo_note} />
        </div>
      </div>
    </section>
  );
}
