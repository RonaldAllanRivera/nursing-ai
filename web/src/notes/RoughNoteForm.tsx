import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useEffect, useState, type ReactNode } from "react";
import { Icon, type IconName } from "../components/Icon";
import { Button } from "../components/ui/Button";
import { patientQuery } from "../patients/patients";
import { failureMessage } from "./draft";
import { createKeyKeeper } from "./idempotency";
import { announceStep, draftJobQuery, isRefused, textState, useSaveRoughNote } from "./roughNote";

const RULED_PAPER = {
  backgroundImage:
    "repeating-linear-gradient(to bottom, transparent 0, transparent calc(var(--lh-note) - 1px), var(--ruled) calc(var(--lh-note) - 1px), var(--ruled) var(--lh-note))",
  backgroundAttachment: "local",
} as const;

const SPOKEN_COUNT = {
  200: "200 or fewer characters remain.",
  100: "100 or fewer characters remain.",
  50: "50 or fewer characters remain.",
  0: "No characters remain.",
  "-1": "Over the limit. Shorten your note to save it.",
} as const;

/** One visible line under the note. Only a failure is a live alert; progress is said by the status region. */
function Line({
  icon,
  tone,
  role,
  children,
}: {
  icon: IconName;
  tone: string;
  role?: "alert";
  children: ReactNode;
}) {
  return (
    <p role={role} className={`flex items-start gap-2 ${tone}`}>
      <Icon name={icon} className="mt-1" />
      <span>{children}</span>
    </p>
  );
}

/** The nurse's rough note on ruled paper, one primary button, and the draft's progress after it. */
export function RoughNoteForm({ patientId }: { patientId: string }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [text, setText] = useState("");
  const [sentText, setSentText] = useState<string | null>(null);
  const [keeper] = useState(() => createKeyKeeper());
  const save = useSaveRoughNote(patientId, (sent) => {
    keeper.done();
    setSentText(sent);
  });
  const job = useQuery({ ...draftJobQuery(save.data?.id ?? ""), enabled: save.isSuccess });

  const { left, showCount, canSave } = textState(text);
  const failed = job.data?.status === "failed";
  // The job can't be followed any more (the server says it is not there): the note is still saved.
  const lost = job.data === undefined && isRefused(job.error);
  const drafting = save.isSuccess && !failed && !lost;
  const busy = save.isPending || drafting;
  // A note that was sent and saved is never sent again as it is: it needs a change first.
  const sameAsSent = save.isSuccess && text === sentText;
  const noteId = job.data?.status === "succeeded" ? job.data.note_id : null;

  useEffect(() => {
    if (noteId === null) return;
    // The notes list on the patient page is out of date now; refresh it for when she comes back.
    void queryClient.invalidateQueries({ queryKey: patientQuery(patientId).queryKey });
    void navigate({ to: "/notes/$noteId", params: { noteId } });
  }, [noteId, patientId, queryClient, navigate]);

  useEffect(() => {
    if (!failed) return;
    // The saved note, with its failure, belongs in this shift's list.
    void queryClient.invalidateQueries({ queryKey: patientQuery(patientId).queryKey });
  }, [failed, patientId, queryClient]);

  const send = () => {
    if (!canSave || busy || sameAsSent) return;
    save.mutate({ text, key: keeper.keyFor(text) });
  };

  const refused = isRefused(save.error);
  const step = announceStep(left);
  const showAgainHint = (failed || lost) && sameAsSent;

  // What a screen reader hears, in one region that is always on the page (a node that appears is
  // often not read; a change in a node that was there is). The words differ from the visible
  // lines on purpose, so the page does not say the same thing twice. Failures are alerts instead.
  const spoken = showAgainHint
    ? "To save a new note, change the text in the box."
    : save.isPending && !save.isPaused
      ? "Saving your note."
      : save.isPaused
        ? "Waiting for the network."
        : drafting && job.isError
          ? "Couldn't check on the draft just now. Still trying."
          : drafting
            ? "Drafting your note."
            : step === null
              ? ""
              : SPOKEN_COUNT[String(step) as keyof typeof SPOKEN_COUNT];
  const [announcement, setAnnouncement] = useState("");
  // Clear, then set on the next frame (the same way as the trace view), so a repeat is read again.
  useEffect(() => {
    let second = 0;
    const first = requestAnimationFrame(() => {
      setAnnouncement("");
      second = requestAnimationFrame(() => {
        setAnnouncement(spoken);
      });
    });
    return () => {
      cancelAnimationFrame(first);
      cancelAnimationFrame(second);
    };
  }, [spoken]);

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
        readOnly={busy}
        aria-readonly={busy}
        rows={8}
        aria-describedby={`rough-note-hint rough-note-count${showAgainHint ? " rough-note-again" : ""}`}
        spellCheck
        className="mt-3 block max-h-[60vh] min-h-64 w-full resize-y rounded-control border border-rule-strong bg-sheet px-3 font-note text-18 leading-(--lh-note) text-ink read-only:text-ink-2"
        style={RULED_PAPER}
      />
      <p
        id="rough-note-count"
        className={`mt-1 min-h-6 text-14 ${left < 0 ? "font-semibold text-stop" : "text-ink-2"}`}
      >
        {showCount
          ? left >= 0
            ? `${String(left)} ${left === 1 ? "character" : "characters"} left`
            : `${String(-left)} ${left === -1 ? "character" : "characters"} too many. Shorten your note to save it.`
          : ""}
      </p>
      {/* Always on the page. The count is said only at 200, 100, 50, 0 and over: a screen reader would otherwise read every keystroke. */}
      <p role="status" className="sr-only">
        {announcement}
      </p>

      <div className="mt-3 grid gap-3">
        {save.isPending && !save.isPaused ? (
          <Line icon="box" tone="text-ink-2">
            Saving your note…
          </Line>
        ) : null}
        {save.isPaused ? (
          <Line icon="flag" tone="text-review">
            Waiting for the network. Your note is still here.
          </Line>
        ) : null}
        {save.isError ? (
          <Line icon="flag" tone="font-semibold text-stop" role="alert">
            {refused
              ? "The note was not accepted. Your note is still here."
              : "Couldn't reach the server. Your note is still here."}
          </Line>
        ) : null}
        {drafting && !job.isError ? (
          <Line icon="box" tone="text-ink-2">
            Drafting your note. This usually takes a few seconds.
          </Line>
        ) : null}
        {drafting && job.isError ? (
          <Line icon="flag" tone="text-review">
            Couldn't check on the draft just now. Your note is saved. Still trying.
          </Line>
        ) : null}
        {lost ? (
          <Line icon="flag" tone="font-semibold text-stop" role="alert">
            Couldn't find the draft. Your note is saved. Reload the page to see where it is.
          </Line>
        ) : null}
        {failed ? (
          <Line icon="flag" tone="font-semibold text-stop" role="alert">
            {failureMessage(job.data?.failure)}
          </Line>
        ) : null}
        {showAgainHint ? (
          <p id="rough-note-again" className="text-ink-2">
            To save a new note, change the text.
          </p>
        ) : null}

        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" variant="primary" disabled={!canSave || busy || sameAsSent}>
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
