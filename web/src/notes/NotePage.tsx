import { Link, useParams } from "@tanstack/react-router";

/** A placeholder until the trace view (W4): just the note's id and a way back. */
export function NotePage() {
  const { noteId } = useParams({ from: "/app/notes/$noteId" });
  return (
    <section>
      <Link
        to="/patients"
        className="inline-flex min-h-11 items-center font-semibold text-pen underline underline-offset-4"
      >
        Back to the patients
      </Link>
      <h1 className="mt-2 text-24 leading-tight font-bold">Note {noteId}</h1>
    </section>
  );
}
