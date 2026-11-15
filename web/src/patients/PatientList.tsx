import { Link } from "@tanstack/react-router";
import { BedTab } from "../components/BedTab";
import { SyntheticTag } from "../components/SyntheticTag";
import { Skeleton } from "../components/ui/Skeleton";
import { useFacility } from "../facility/useFacility";
import { formatShiftRange } from "../region/format";
import { words } from "../region/words";
import { useSession } from "../session/session";
import { usePatients } from "./patients";

/** The ward as a dense bed list on ruled paper: the bed tab, the name, age and sex, the ward. */
export function PatientList() {
  const { data: session } = useSession();
  const facility = useFacility(session?.facility_key ?? null);
  const patients = usePatients();

  if (facility.isError) {
    return (
      <p role="alert" className="pt-2 text-stop">
        The ward details did not load. Reload the page to try again.
      </p>
    );
  }
  if (!facility.data) {
    return (
      <div aria-busy="true" className="grid gap-3 pt-2">
        <span className="sr-only">Loading the patients…</span>
        <Skeleton className="h-8 w-2/3" />
        <Skeleton className="h-16" />
        <Skeleton className="h-16" />
      </div>
    );
  }

  const { locale, clock } = facility.data.profile;
  const w = words(locale);

  return (
    <section aria-labelledby="patients-heading">
      <h1 id="patients-heading" className="text-24 leading-tight font-bold">
        {w.patientsHeading}
      </h1>
      {session?.shift ? (
        <p className="mt-1 text-ink-2">{formatShiftRange(session.shift, { locale, clock })}</p>
      ) : null}

      <div className="mt-4 overflow-hidden rounded-sheet border border-rule bg-sheet shadow-(--lift)">
        {patients.isPending ? (
          <div aria-busy="true" className="grid gap-px p-3">
            <span className="sr-only">Loading the patients…</span>
            <Skeleton className="h-14" />
            <Skeleton className="h-14" />
          </div>
        ) : patients.isError ? (
          <p role="alert" className="p-4 text-stop">
            The patients did not load. Reload the page to try again.
          </p>
        ) : patients.data.length === 0 ? (
          <p className="p-4 text-ink-2">
            No patients are listed on this {w.ward.toLowerCase()} yet. They appear here as soon as
            they are admitted.
          </p>
        ) : (
          <ul className="m-0 list-none p-0">
            {patients.data.map((patient) => (
              <li key={patient.id} className="border-b border-ruled last:border-b-0">
                <Link
                  to="/patients/$patientId"
                  params={{ patientId: patient.id }}
                  className="flex min-h-16 flex-wrap items-center gap-x-4 gap-y-1 px-3 py-2 text-ink no-underline hover:bg-sunk"
                >
                  <BedTab word={w.bed} label={patient.bed_label} />
                  <span className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-3 gap-y-1">
                    <span className="text-18 font-bold">{patient.display_name}</span>
                    <SyntheticTag />
                  </span>
                  <span className="flex flex-wrap gap-x-4 text-ink-2">
                    <span>{`${String(patient.age)} ${patient.sex}`}</span>
                    <span>{patient.ward}</span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
