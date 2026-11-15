import { Link } from "@tanstack/react-router";
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

  if (!facility.data) {
    return (
      <div aria-busy="true" className="grid gap-3 pt-2">
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
            <Skeleton className="h-14" />
            <Skeleton className="h-14" />
          </div>
        ) : patients.isError ? (
          <p role="alert" className="p-4 text-stop">
            The patients did not load. Reload the page to try again.
          </p>
        ) : patients.data.length === 0 ? (
          <p className="p-4 text-ink-2">
            No patients on this {w.ward.toLowerCase()} yet. Ask the head nurse to add them.
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
                  <span className="grid min-w-14 flex-none place-items-center rounded-control rounded-bl-[2px] bg-primary px-2 py-1 leading-none text-primary-ink">
                    <span className="text-12 font-medium opacity-85">{w.bed}</span>
                    <span className="text-21 font-bold">{patient.bed_label}</span>
                  </span>
                  <span className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-3 gap-y-1">
                    <span className="text-18 font-bold">{patient.display_name}</span>
                    <span className="rounded-full border border-dashed border-rule-strong px-2 text-14 font-semibold text-ink-2">
                      Synthetic
                    </span>
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
