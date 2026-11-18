import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { ApiError } from "../api/errors";
import { Icon } from "../components/Icon";
import { Skeleton } from "../components/ui/Skeleton";
import { Button } from "../components/ui/Button";
import { words } from "../region/words";
import { asksPinAgain } from "../session/pin";
import { explainDemoEnd, signInOptionsQuery, useSession } from "../session/session";
import { checkShifts } from "./checkShifts";
import { facilitySettingsQuery, useResetFacility, useSaveFacility } from "./facilities";
import { Field, INPUT, RadioGroup } from "./fields";
import {
  mapProblems,
  resetFailureText,
  saveFailureText,
  settingsSchema,
  timeZoneSuggestions,
  toFormValues,
  toSettings,
  type FormValues,
} from "./form";
import { PinDialog } from "./PinDialog";
import { RESET_DONE, RESET_DROPS, RESET_QUESTION, RESET_TITLE, canResetDemo } from "./resetDemo";
import { ShiftsTable } from "./ShiftsTable";

const LOCALES = [
  { value: "en-PH", label: "English (Philippines)" },
  { value: "en-US", label: "English (United States)" },
] as const;
const TEMPERATURES = [
  { value: "Cel", label: "°C" },
  { value: "[degF]", label: "°F" },
] as const;
const WEIGHTS = [
  { value: "kg", label: "kg" },
  { value: "[lb_av]", label: "lb" },
  { value: "none", label: "None" },
] as const;
const CLOCKS = [
  { value: "24h", label: "24-hour" },
  { value: "12h", label: "12-hour" },
] as const;

/** The refusal's problem code, when the server named one. */
function problemCode(error: unknown): string | undefined {
  return error instanceof ApiError ? error.problem?.code : undefined;
}

/** A card on the ruled page: a heading and what belongs under it. */
function Sheet({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  return (
    <section
      aria-labelledby={id}
      className="rounded-sheet border border-rule bg-sheet p-4 shadow-(--lift) sm:p-5"
    >
      <h2 id={id} className="text-18 leading-tight font-bold">
        {title}
      </h2>
      <div className="mt-3 grid gap-4">{children}</div>
    </section>
  );
}

type Failure = "stale" | "reload" | "other" | null;

function Editor({
  facilityKey,
  loaded,
  onDirtyChange,
}: {
  facilityKey: string;
  loaded: { facility: Parameters<typeof toFormValues>[0]; etag: string | null };
  onDirtyChange: (dirty: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const { data: session } = useSession();
  const signInOptions = useQuery(signInOptionsQuery);
  const persona = session?.kind === "persona";
  const showReset = canResetDemo(session, signInOptions.data);
  const schema = useMemo(() => settingsSchema(), []);
  const zones = useMemo(
    () => timeZoneSuggestions(loaded.facility.profile.timezone),
    [loaded.facility.profile.timezone],
  );
  // The version this form was loaded from (or last saved as): what the next save is made against.
  const [etag, setEtag] = useState(loaded.etag);
  const formElement = useRef<HTMLFormElement>(null);
  const problemsElement = useRef<HTMLDivElement>(null);
  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: toFormValues(loaded.facility),
  });
  const { register, handleSubmit, setError, reset, control, formState } = form;
  const { errors, isDirty } = formState;

  // The last thing that worked, for the line beside the buttons.
  const [done, setDone] = useState<{ what: "saved" | "reset"; version: string } | null>(null);
  // The settings the PIN dialog is about to save, or whether it is about to put the demo back.
  const [asking, setAsking] = useState<FormValues | null>(null);
  const [resetting, setResetting] = useState(false);
  const saveButton = useRef<HTMLButtonElement>(null);
  const resetButton = useRef<HTMLButtonElement>(null);
  // A dialog giving the focus back must not take it from the field a refusal just sent it to.
  const focusMoved = useRef(false);
  const [failure, setFailure] = useState<Failure>(null);
  const [otherText, setOtherText] = useState("");
  const [reloading, setReloading] = useState(false);
  const [serverTable, setServerTable] = useState<string[]>([]);
  const [serverOther, setServerOther] = useState<string[]>([]);
  // What to focus after the next render: the rendered result of a send is what gets the focus.
  const focusWanted = useRef<"field" | "table" | null>(null);
  const [focusTick, setFocusTick] = useState(0);
  const focusAfterRender = (what: "field" | "table") => {
    focusWanted.current = what;
    setFocusTick((tick) => tick + 1);
  };

  useEffect(() => {
    onDirtyChange(isDirty);
  }, [isDirty, onDirtyChange]);

  const values = useWatch({ control });
  const local = checkShifts(
    (values.shifts ?? []).map((s) => ({
      code: s.code ?? "",
      starts_local: s.starts_local ?? "",
      ends_local: s.ends_local ?? "",
    })),
    values.day_starts_at ?? "",
    values.clock ?? "24h",
  );
  const problems = [...local, ...serverTable.filter((message) => !local.includes(message))];

  // After a send the first thing to fix gets the focus (the server's field errors are set a
  // moment before this runs, so their inputs are already marked invalid).
  useEffect(() => {
    const wanted = focusWanted.current;
    focusWanted.current = null;
    if (wanted === "table") problemsElement.current?.focus();
    else if (wanted === "field") {
      formElement.current
        ?.querySelector<HTMLElement>('[aria-invalid="true"], fieldset[data-invalid] input')
        ?.focus();
    }
  }, [focusTick]);

  /** The form checked out: now ask for the PIN (nothing is sent until it is typed). */
  const send = (submitted: FormValues) => {
    setFailure(null);
    setServerOther([]);
    if (local.length > 0) {
      focusAfterRender("table");
      return;
    }
    focusMoved.current = false;
    setAsking(submitted);
  };

  /** A refusal that is not a wrong PIN: the dialog is done, and the form says what to fix. */
  const refused = (error: unknown) => {
    setAsking(null);
    const status = error instanceof ApiError ? error.status : null;
    const mapped = mapProblems(
      error instanceof ApiError && status === 422 ? (error.problem?.errors ?? []) : [],
    );
    const named = mapped.fields.length + mapped.table.length + mapped.other.length > 0;
    if (status === 412) {
      setFailure("stale");
    } else if (status === 422 && named) {
      for (const { name, message } of mapped.fields) {
        setError(name as `shifts.${number}.code`, { type: "server", message });
      }
      setServerTable(mapped.table);
      setServerOther(mapped.other);
      focusMoved.current = true;
      focusAfterRender(mapped.fields.length > 0 ? "field" : "table");
    } else {
      // Nothing to put next to a field: a plain line says what happened and what to do.
      setOtherText(saveFailureText(status, problemCode(error)));
      setFailure("other");
    }
  };

  const save = useSaveFacility(
    facilityKey,
    () => {
      if (!asking) throw new Error("There is nothing to save.");
      return { etag, body: toSettings(asking) };
    },
    {
      onSuccess: (saved) => {
        setAsking(null);
        setEtag(saved.etag);
        reset(toFormValues(saved.facility));
        setServerTable([]);
        setDone({ what: "saved", version: String(saved.facility.version) });
      },
      onError: (error, previous) => {
        if (persona) explainDemoEnd(queryClient, error, previous);
        if (!asksPinAgain(error)) refused(error);
      },
    },
  );

  const putBack = useResetFacility(facilityKey, () => etag, {
    onSuccess: (saved) => {
      setResetting(false);
      setEtag(saved.etag);
      reset(toFormValues(saved.facility));
      setFailure(null);
      setServerTable([]);
      setServerOther([]);
      setDone({ what: "reset", version: String(saved.facility.version) });
    },
    onError: (error, previous) => {
      if (persona) explainDemoEnd(queryClient, error, previous);
      if (asksPinAgain(error)) return;
      setResetting(false);
      const status = error instanceof ApiError ? error.status : null;
      if (status === 412) {
        setFailure("stale");
      } else {
        setOtherText(resetFailureText(status, problemCode(error)));
        setFailure("other");
      }
    },
  });

  /** Gives the focus back to the button that opened the dialog, unless a refusal sent it to a field. */
  const closeFocus = (event: Event, opener: { current: HTMLButtonElement | null }) => {
    event.preventDefault();
    if (!focusMoved.current) opener.current?.focus();
    focusMoved.current = false;
  };

  const reload = async () => {
    setReloading(true);
    const key = facilitySettingsQuery(facilityKey).queryKey;
    await queryClient.refetchQueries({ queryKey: key, exact: true });
    setReloading(false);
    const latest = queryClient.getQueryData(key);
    if (queryClient.getQueryState(key)?.status === "error" || !latest) {
      setFailure("reload");
      return;
    }
    setEtag(latest.etag);
    reset(toFormValues(latest.facility));
    setFailure(null);
    setServerTable([]);
    setServerOther([]);
  };

  return (
    <>
      <form
        ref={formElement}
        noValidate
        // Editing takes the server's table message away: it described the last send.
        onChange={() => {
          setServerTable([]);
        }}
        onSubmit={(event) => {
          void handleSubmit(send, () => {
            setFailure(null);
          })(event);
        }}
        className="mt-4 grid gap-4"
      >
        <Sheet id="facility-heading" title="The facility">
          <div className="grid gap-4 md:grid-cols-2">
            <Field id="facility-name" label="Facility name" error={errors.name?.message}>
              {(props) => (
                <input
                  type="text"
                  autoComplete="off"
                  className={INPUT}
                  {...props}
                  {...register("name")}
                />
              )}
            </Field>
            <Field id="facility-timezone" label="Timezone" error={errors.timezone?.message}>
              {(props) => (
                <>
                  <input
                    type="text"
                    list="timezone-list"
                    autoComplete="off"
                    spellCheck={false}
                    className={INPUT}
                    {...props}
                    {...register("timezone")}
                  />
                  <datalist id="timezone-list">
                    {zones.map((zone) => (
                      <option key={zone} value={zone} />
                    ))}
                  </datalist>
                </>
              )}
            </Field>
          </div>
          <RadioGroup
            id="facility-locale"
            legend="Locale"
            name="locale"
            choices={LOCALES}
            register={register}
            error={errors.locale?.message}
          />
        </Sheet>

        <Sheet id="shifts-heading" title="Nursing day and shifts">
          <Field
            id="facility-day-starts"
            label="Nursing day starts"
            error={errors.day_starts_at?.message}
            className="max-w-48"
          >
            {(props) => (
              <input type="time" className={INPUT} {...props} {...register("day_starts_at")} />
            )}
          </Field>
          <ShiftsTable form={form} problems={problems} problemsRef={problemsElement} />
        </Sheet>

        <Sheet id="units-heading" title="Units and clock">
          <div className="grid gap-4 md:grid-cols-2">
            <RadioGroup
              id="facility-temperature"
              legend="Temperature"
              name="temperature"
              choices={TEMPERATURES}
              register={register}
              error={errors.temperature?.message}
            />
            <RadioGroup
              id="facility-weight"
              legend="Weight"
              name="weight"
              choices={WEIGHTS}
              register={register}
              error={errors.weight?.message}
            />
            <p>
              <span className="mb-1 block text-14 font-semibold text-ink-2">Volume</span>
              mL
            </p>
            <RadioGroup
              id="facility-clock"
              legend="Clock"
              name="clock"
              choices={CLOCKS}
              register={register}
              error={errors.clock?.message}
            />
          </div>
          <p>
            <span className="mb-1 block text-14 font-semibold text-ink-2">Note format</span>
            <span className="font-semibold">
              {words(values.locale ?? loaded.facility.profile.locale).noteFormat("fdar")}
            </span>{" "}
            <span className="ml-3 text-ink-2">More formats come later</span>
          </p>
        </Sheet>

        <Sheet id="session-heading" title="Staying signed in">
          <Field
            id="facility-session-hours"
            label="Sign nurses out after (hours)"
            error={errors.session_max_hours?.message}
            hint="Applies to sessions that start after you save."
            className="max-w-48"
          >
            {(props) => (
              <input
                type="number"
                inputMode="numeric"
                min={1}
                max={24}
                step={1}
                className={INPUT}
                {...props}
                {...register("session_max_hours", { valueAsNumber: true })}
              />
            )}
          </Field>
        </Sheet>

        {serverOther.length > 0 ? (
          <ul role="alert" className="m-0 grid list-none gap-1 p-0 text-stop">
            {serverOther.map((message, at) => (
              <li key={`${String(at)}-${message}`} className="flex items-start gap-2">
                <Icon name="flag" className="mt-0.5" />
                {message}
              </li>
            ))}
          </ul>
        ) : null}

        {failure === "stale" || failure === "reload" ? (
          <div
            role="alert"
            className="rounded-control border border-stop bg-stop-tint p-3 text-stop"
          >
            <p className="flex items-start gap-2 font-semibold">
              <Icon name="flag" className="mt-0.5" />
              <span>
                {failure === "stale"
                  ? "Someone else changed the settings. Reload to see them."
                  : "The settings did not reload. Try again."}
              </span>
            </p>
            <p className="mt-1">Your changes are still in the form. Reloading replaces them.</p>
            <Button
              className="mt-2"
              aria-disabled={reloading || undefined}
              onClick={() => {
                if (!reloading) void reload();
              }}
            >
              {reloading ? "Reloading…" : "Reload settings"}
            </Button>
          </div>
        ) : null}
        {failure === "other" ? (
          <p role="alert" className="flex items-start gap-2 text-stop">
            <Icon name="flag" className="mt-0.5" />
            {otherText}
          </p>
        ) : null}

        <div className="flex flex-wrap items-center gap-3">
          <Button ref={saveButton} type="submit" variant="primary">
            Save settings
          </Button>
          {showReset ? (
            <Button
              ref={resetButton}
              onClick={() => {
                focusMoved.current = false;
                setResetting(true);
              }}
            >
              {RESET_TITLE}
            </Button>
          ) : null}
          <p role="status" className="flex items-center gap-2 font-semibold text-ok">
            {done !== null && !isDirty ? (
              <>
                <Icon name="check" />
                <span>{done.what === "saved" ? "Saved." : RESET_DONE}</span>
                <span className="font-normal text-ink-2">Settings version {done.version}.</span>
              </>
            ) : null}
          </p>
        </div>
      </form>
      {/* Outside the form: a dialog's events would otherwise reach the form through React's tree. */}
      <PinDialog
        open={asking !== null}
        onCancel={() => {
          setAsking(null);
        }}
        words={{
          title: "Enter your PIN to save these settings",
          question: "Your PIN proves it's you changing this facility.",
          confirm: "Save settings",
          busy: "Saving…",
        }}
        request={save}
        persona={persona}
        onCloseAutoFocus={(event) => {
          closeFocus(event, saveButton);
        }}
      />
      <PinDialog
        open={resetting}
        onCancel={() => {
          setResetting(false);
        }}
        words={{
          title: RESET_TITLE,
          question: RESET_QUESTION,
          note: isDirty ? RESET_DROPS : null,
          confirm: "Reset settings",
          busy: "Resetting…",
        }}
        request={putBack}
        persona={persona}
        onCloseAutoFocus={(event) => {
          closeFocus(event, resetButton);
        }}
      />
    </>
  );
}

/** One facility's settings, loaded with its ETag. Shows the form only when there are settings to show. */
export function FacilityForm({
  facilityKey,
  onDirtyChange,
}: {
  facilityKey: string;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const settings = useQuery(facilitySettingsQuery(facilityKey));
  if (settings.data) {
    return (
      <Editor facilityKey={facilityKey} loaded={settings.data} onDirtyChange={onDirtyChange} />
    );
  }
  if (settings.isError) {
    return (
      <div role="alert" className="mt-4 grid justify-items-start gap-2 text-stop">
        <p className="flex items-start gap-2">
          <Icon name="flag" className="mt-0.5" />
          This facility's settings did not load.
        </p>
        <Button
          aria-disabled={settings.isFetching || undefined}
          onClick={() => {
            if (!settings.isFetching) void settings.refetch();
          }}
        >
          {settings.isFetching ? "Trying again…" : "Try again"}
        </Button>
      </div>
    );
  }
  return (
    <div aria-busy="true" className="mt-4 grid gap-3">
      <span className="sr-only">Loading the settings…</span>
      <Skeleton className="h-24" />
      <Skeleton className="h-40" />
    </div>
  );
}
