import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { ApiError } from "../api/errors";
import { Button } from "../components/ui/Button";
import { failureMessage } from "./draft";
import { createKeyKeeper } from "./idempotency";
import { patientQuery } from "../patients/patients";
import { draftJobQuery, textState, useSaveRoughNote } from "./roughNote";

const RULED_PAPER = {
  backgroundImage:
    "repeating-linear-gradient(to bottom, transparent 0, transparent calc(var(--lh-note) - 1px), var(--ruled) calc(var(--lh-note) - 1px), var(--ruled) var(--lh-note))",
  backgroundAttachment: "local",
} as const;

/** The nurse's rough note on ruled paper, one primary button, and the draft's progress after it. */
export function RoughNoteForm({ patientId }: { patientId: string }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [text, setText] = useState("");
  const [keeper] = useState(() => createKeyKeeper());
  const save = useSaveRoughNote(patientId, () => {
    keeper.done();
  });
  const job = useQuery({ ...draftJobQuery(save.data?.id ?? ""), enabled: save.isSuccess });

  const { left, showCount, canSave } = textState(text);
  const failed = job.data?.status === "failed";
  const drafting = save.isSuccess && !failed;
  const busy = save.isPending || drafting;
  const noteId = job.data?.status === "succeeded" ? job.data.note_id : null;

  useEffect(() => {
    if (noteId === null) return;
    // The notes list on the patient page is out of date now; refresh it for when she comes back.
    void queryClient.invalidateQueries({ queryKey: patientQuery(patientId).queryKey });
    void navigate({ to: "/notes/$noteId", params: { noteId } });
  }, [noteId, patientId, queryClient, navigate]);

  const send = () => {
    if (!canSave || busy) return;
    save.mutate({ text, key: keeper.keyFor(text) });
  };

  // A 4xx (not a 401, which signs you out) is not worth sending again as it is.
  const refused = save.error instanceof ApiError && save.error.status < 500;

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        send();
      }}
      className="rounded-sheet border border-rule bg-sheet p-4 shadow-(--lift) sm:p-5"
    >
      <label htmlFor="rough-note" className="text-18 font-bold">
        Your note
      </label>
      <p id="rough-note-hint" className="text-14 text-ink-2">
        Write it the way you would on a scrap of paper. The draft is made from it.
      </p>
      <textarea
        id="rough-note"
        value={text}
        onChange={(event) => {
          setText(event.target.value);
        }}
        rows={8}
        aria-describedby="rough-note-hint rough-note-count"
        spellCheck
        className="mt-3 block max-h-[60vh] min-h-64 w-full resize-y rounded-control border border-rule-strong bg-sheet px-3 font-note text-18 leading-(--lh-note) text-ink"
        style={RULED_PAPER}
      />
      <p
        id="rough-note-count"
        aria-live="polite"
        className={`mt-1 min-h-6 text-14 ${left < 0 ? "font-semibold text-stop" : "text-ink-2"}`}
      >
        {showCount
          ? left >= 0
            ? `${String(left)} ${left === 1 ? "character" : "characters"} left`
            : `${String(-left)} ${left === -1 ? "character" : "characters"} too many. Shorten your note to save it.`
          : ""}
      </p>

      <div className="mt-3 grid gap-3">
        {save.isError ? (
          <p role="alert" className="font-semibold text-stop">
            {refused
              ? "The note was not accepted. Your note is still here."
              : "Couldn't reach the server. Your note is still here."}
          </p>
        ) : null}
        {drafting && !job.isError ? (
          <p role="status" className="text-ink-2">
            Drafting your note. This usually takes a few seconds.
          </p>
        ) : null}
        {drafting && job.isError ? (
          <p role="status" className="text-ink-2">
            Couldn't check on the draft just now. Your note is saved. Still trying.
          </p>
        ) : null}
        {failed ? (
          <p role="alert" className="font-semibold text-stop">
            {failureMessage(job.data?.failure)}
          </p>
        ) : null}

        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" variant="primary" disabled={!canSave || busy}>
            Save note
          </Button>
          {save.isError && !refused ? (
            <Button onClick={send} disabled={!canSave}>
              Try again
            </Button>
          ) : null}
        </div>
      </div>
    </form>
  );
}
