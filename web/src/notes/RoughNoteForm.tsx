import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Icon, type IconName } from "../components/Icon";
import { Button } from "../components/ui/Button";
import { patientQuery } from "../patients/patients";
import { DemoNoteButton } from "./DemoNoteButton";
import { failureMessage } from "./draft";
import { draftAgainOutcome, isAlreadyDrafted, useDraftAgain } from "./draftAgain";
import { holdNote, readHeldNote } from "./heldNote";
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

// The visible lines and the status region say these sentences from the same constants, so they can't drift.
const WAITING = "Waiting for the network.";
const NOTE_STILL_HERE = "Your note is still here.";
const DRAFTING = "Drafting your note.";
const FEW_SECONDS = "This usually takes a few seconds.";
const COULDNT_CHECK = "Couldn't check on the draft just now.";
const NOTE_SAVED = "Your note is saved.";
const STILL_TRYING = "Still trying.";
/** What became of the earlier note while she writes the next one. */
const EARLIER_DRAFTED = "Your earlier note has its draft.";
const EARLIER_DRAFTING = "Your earlier note is being drafted again.";

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
export function RoughNoteForm({
  patientId,
  demoNote = null,
}: {
  patientId: string;
  /** The demo case's rough note, for a demo patient: "Use the demo note" offers it. */
  demoNote?: string | null;
}) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  // What she had typed and not sent comes back after a gate screen replaced this page.
  const [text, setText] = useState(() => readHeldNote(queryClient, patientId));
  const [sentText, setSentText] = useState<string | null>(null);
  const [keeper] = useState(() => createKeyKeeper());
  // The draft job being followed: the newest one this form started (a save, or a try again).
  const [jobId, setJobId] = useState("");
  // The job the server said was already drafted somewhere else (another tab, the list's button).
  const [draftedElsewhereFor, setDraftedElsewhereFor] = useState("");
  const again = useDraftAgain(patientId);
  const save = useSaveRoughNote(patientId, (sent, started) => {
    keeper.done();
    setSentText(sent);
    setJobId(started.id);
    // A refused try again (the daily limit) was about the note before this one.
    again.reset();
    // Sent, so it is no longer unsent text to hold.
    holdNote(queryClient, patientId, "");
  });
  const box = useRef<HTMLTextAreaElement>(null);
  const job = useQuery({ ...draftJobQuery(jobId), enabled: jobId !== "" });
  // What the shift list says is the newest job of this rough note (another tab, or the list's own button, may have started one).
  const detail = useQuery({ ...patientQuery(patientId), enabled: false });

  const { left, showCount, canSave } = textState(text);
  const failed = job.data?.status === "failed";
  // The job can't be followed any more (the server says it is not there): the note is still saved.
  const lost = job.data === undefined && isRefused(job.error);
  const drafting = save.isSuccess && !failed && !lost;
  const busy = save.isPending || drafting || again.isPending;
  // A note that was sent and saved is never sent again as it is: it needs a change first.
  const sameAsSent = save.isSuccess && text === sentText;
  const noteId = job.data?.status === "succeeded" ? job.data.note_id : null;
  const newest = detail.data?.notes.find((n) => n.rough_note_id === job.data?.rough_note_id)?.job;
  // The list was read after this job was last seen, and names a newer job for the same note: follow
  // that one, unless she has gone on to other text.
  const listIsNewer = detail.dataUpdatedAt > job.dataUpdatedAt;
  const hasNewer = newest !== undefined && newest.id !== jobId;
  const followTarget = failed && sameAsSent && listIsNewer && hasNewer ? newest.id : undefined;
  if (followTarget !== undefined) setJobId(followTarget);
  // The earlier note's newest job, when the list names a newer one than the job followed here.
  const newer = listIsNewer && hasNewer ? newest : undefined;
  // She has gone on to other text, and the earlier note was tried again somewhere else (another
  // tab, the list's button): its old failure is history. It has its draft only once that job
  // succeeded (a 409 `already_drafted` says so too); while the job runs it is being drafted again.
  const earlier =
    !failed || sameAsSent
      ? null
      : draftedElsewhereFor === jobId || newer?.status === "succeeded"
        ? "drafted"
        : newer !== undefined && newer.status !== "failed"
          ? "drafting"
          : null;
  // The failure to show is the earlier note's newest: a newer try that failed too says why it did.
  const failedJob = !sameAsSent && newer?.status === "failed" ? newer : job.data;
  // While a new note saves the last one's failure is not the news.
  const showFailure = failed && earlier === null && !save.isPending;
  // Only a failure worth another try offers it; the same text would fail the same way otherwise.
  const canDraftAgain = showFailure && failedJob?.retryable === true;
  // One primary at a time: re-drafting the saved note while its text is as sent, Save note once she has edited it.
  const savePrimary = !canDraftAgain || !sameAsSent;

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

  const tryDraftingAgain = () => {
    const roughNoteId = job.data?.rough_note_id;
    if (roughNoteId === undefined) return;
    // The button goes once the new job starts: the cursor goes to the note, where the progress is read out.
    box.current?.focus();
    const followed = jobId;
    again.ask(roughNoteId, {
      onSuccess: (started) => {
        setJobId(started.id);
      },
      onError: (error) => {
        if (isAlreadyDrafted(error)) setDraftedElsewhereFor(followed);
      },
    });
  };
  const againWords = again.isError ? draftAgainOutcome(again.error) : null;

  const refused = isRefused(save.error);
  const step = announceStep(left);
  const showAgainHint = (failed || lost) && sameAsSent && !canDraftAgain;

  // What a screen reader hears, in one region that is always on the page (a node that appears is
  // often not read; a change in a node that was there is). For the progress lines (waiting,
  // drafting, couldn't check) it says the same sentences as the visible line, word for word. The
  // saving line, the change-the-text hint and the count are worded for the ear. Failures are
  // alerts instead.
  const spoken = showAgainHint
    ? "To save a new note, change the text in the box."
    : save.isPending && !save.isPaused
      ? "Saving your note."
      : save.isPaused
        ? `${WAITING} ${NOTE_STILL_HERE}`
        : drafting && job.isError
          ? `${COULDNT_CHECK} ${NOTE_SAVED} ${STILL_TRYING}`
          : drafting
            ? `${DRAFTING} ${FEW_SECONDS}`
            : step === null
              ? ""
              : SPOKEN_COUNT[String(step) as keyof typeof SPOKEN_COUNT];
  const [announcement, setAnnouncement] = useState("");
  // Clear, then set on the next frame (the same way as the trace view), so a change of words is read
  // as new. This runs only when `spoken` changes, so the same words are not read again.
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
      {demoNote !== null ? (
        <div className="mt-3">
          <DemoNoteButton
            hasTyped={text.trim().length > 0}
            disabled={busy}
            putInBox={() => {
              setText(demoNote);
              holdNote(queryClient, patientId, demoNote);
            }}
            focusBox={() => box.current?.focus()}
          />
        </div>
      ) : null}
      <textarea
        ref={box}
        id="rough-note"
        value={text}
        onChange={(event) => {
          setText(event.target.value);
          holdNote(queryClient, patientId, event.target.value);
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
      {/* What became of the earlier note, in a region that is always on the page, so a screen
          reader hears the line when it comes or changes (the 409 path moves the cursor to the
          note box, and no alert says it). It takes no room while it is empty. */}
      <div aria-live="polite">
        {earlier !== null ? (
          <div className="mt-3">
            <Line icon={earlier === "drafted" ? "check" : "box"} tone="text-ink-2">
              {earlier === "drafted" ? EARLIER_DRAFTED : EARLIER_DRAFTING}
              {earlier === "drafted" &&
              newest?.status === "succeeded" &&
              newest.note_id !== null ? (
                <>
                  {" "}
                  <Link
                    to="/notes/$noteId"
                    params={{ noteId: newest.note_id }}
                    className="inline-flex min-h-11 items-center text-pen underline underline-offset-4"
                  >
                    Open it
                  </Link>
                </>
              ) : null}
            </Line>
          </div>
        ) : null}
      </div>

      <div className="mt-3 grid gap-3">
        {save.isPending && !save.isPaused ? (
          <Line icon="box" tone="text-ink-2">
            Saving your note…
          </Line>
        ) : null}
        {save.isPaused ? (
          <Line icon="flag" tone="text-review">
            {WAITING} {NOTE_STILL_HERE}
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
            {DRAFTING} {FEW_SECONDS}
          </Line>
        ) : null}
        {drafting && job.isError ? (
          <Line icon="flag" tone="text-review">
            {COULDNT_CHECK} {NOTE_SAVED} {STILL_TRYING}
          </Line>
        ) : null}
        {lost ? (
          <Line icon="flag" tone="font-semibold text-stop" role="alert">
            Couldn't find the draft. Your note is saved. Reload the page to see where it is.
          </Line>
        ) : null}
        {showFailure ? (
          <Line icon="flag" tone="font-semibold text-stop" role="alert">
            {failureMessage(failedJob?.failure)}
          </Line>
        ) : null}
        {againWords?.kind === "words" ? (
          <Line icon="flag" tone="font-semibold text-stop" role="alert">
            {againWords.words}
          </Line>
        ) : null}
        {showAgainHint ? (
          <p id="rough-note-again" className="text-ink-2">
            To save a new note, change the text.
          </p>
        ) : null}

        <div className="flex flex-wrap items-center gap-3">
          {canDraftAgain ? (
            <Button
              variant={savePrimary ? "quiet" : "primary"}
              disabled={again.isPending}
              onClick={tryDraftingAgain}
            >
              Try drafting again
            </Button>
          ) : null}
          <Button
            id="rough-note-save"
            type="submit"
            variant={savePrimary ? "primary" : "quiet"}
            disabled={!canSave || busy || sameAsSent}
          >
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
