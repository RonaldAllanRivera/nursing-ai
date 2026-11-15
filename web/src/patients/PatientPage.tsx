import { Link, useParams } from "@tanstack/react-router";
import { Skeleton } from "../components/ui/Skeleton";
import { usePatients } from "./patients";

/** A placeholder until the patient's shift page is built: the patient's name and a way back. */
export function PatientPage() {
  const { patientId } = useParams({ from: "/app/patients/$patientId" });
  const patients = usePatients();
  const patient = patients.data?.find((p) => p.id === patientId);

  return (
    <section>
      <Link
        to="/patients"
        className="inline-flex min-h-11 items-center font-semibold text-pen underline underline-offset-4"
      >
        Back to the patients
      </Link>
      {patients.isPending ? (
        <Skeleton className="mt-2 h-8 w-1/2" />
      ) : patient ? (
        <h1 className="mt-2 text-24 leading-tight font-bold">{patient.display_name}</h1>
      ) : (
        <p className="mt-2 text-ink-2">This patient is not on your list. Go back and pick one.</p>
      )}
    </section>
  );
}
