import { useRef, useState } from "react";
import type { components } from "../api/schema";
import { ApiError } from "../api/errors";
import { Button } from "../components/ui/Button";
import { roleLabel } from "../session/personas";
import { Field, INPUT } from "../settings/fields";
import { PinDialog } from "../settings/PinDialog";
import {
  EMAIL_PROBLEM,
  EMAIL_TAKEN,
  FACILITY_PROBLEM,
  validateInvite,
  type InviteProblems,
  type InviteValues,
} from "./invite";
import { pinProblemMessage } from "../session/pin";
import { failureKind } from "./failure";
import { useInvite } from "./staffApi";
import { DONE, inviteWords } from "./words";

const ROLES: components["schemas"]["Role"][] = ["staff_nurse", "head_nurse", "admin"];
const EMPTY: InviteValues = { email: "", role: "staff_nurse", facility: "" };

/** Said under the PIN when the server refused the invite's content in a way the form has no field for. */
export const INVITE_UNSAVED =
  "The invite could not be saved as typed. Check the email, role and facility, then try again.";

/** The words for a failure that keeps the dialog open: a refused invite, or the usual PIN words. */
function inviteFailureWords(error: unknown): string {
  return error instanceof ApiError && error.status === 422
    ? INVITE_UNSAVED
    : pinProblemMessage(error, false);
}

/**
 * What a refused invitation says about the form, in the screen's own words (never the server's),
 * or `null` when the refusal is not about a field the form has.
 */
function problemsFrom(error: unknown): InviteProblems | null {
  if (!(error instanceof ApiError)) return null;
  if (error.status === 409 && error.problem?.code === "email_taken") return { email: EMAIL_TAKEN };
  if (error.status !== 422) return null;
  const fields = (error.problem?.errors ?? []).map((e) => e.field);
  const found: InviteProblems = {};
  if (fields.includes("body.email")) found.email = EMAIL_PROBLEM;
  if (fields.includes("body.facility_key")) found.facility = FACILITY_PROBLEM;
  return found.email || found.facility ? found : null;
}

/**
 * The admin's invitation: email, role, facility (nurses only). The form is checked before the PIN
 * is asked for. A taken email is said under the email field, with what was typed kept.
 */
export function InviteForm({
  facilities,
  onDone,
  onStale,
}: {
  facilities: { key: string; name: string }[];
  onDone: (words: string) => void;
  onStale: () => void;
}) {
  const [values, setValues] = useState<InviteValues>(EMPTY);
  const [problems, setProblems] = useState<InviteProblems>({});
  const [asking, setAsking] = useState(false);
  const email = useRef<HTMLInputElement>(null);
  const facility = useRef<HTMLSelectElement>(null);
  const submit = useRef<HTMLButtonElement>(null);
  const landing = useRef<"email" | "facility" | "invite">("invite");

  const change = (next: Partial<InviteValues>) => {
    setValues((v) => ({ ...v, ...next }));
    setProblems({});
  };

  const request = useInvite(() => values, {
    onSuccess: (row) => {
      landing.current = "email";
      setAsking(false);
      setValues(EMPTY);
      onDone(DONE.invited(row.email));
    },
    onError: (error) => {
      const kind = failureKind(error);
      if (kind === "wrong_pin") return;
      const about = problemsFrom(error);
      if (about) {
        // The first field with a problem, in the order the form shows them, takes the focus.
        landing.current = about.email ? "email" : "facility";
        setAsking(false);
        setProblems(about);
      } else if (kind === "gate" || kind === "stale") {
        setAsking(false);
        if (kind === "stale") onStale();
      }
      // Anything else (no connection, a server error): the dialog stays, with its own words.
    },
  });

  const facilityName =
    values.role === "admin"
      ? null
      : (facilities.find((f) => f.key === values.facility)?.name ?? null);
  const asked = values.email.trim();

  return (
    <section
      aria-labelledby="invite-heading"
      className="mt-4 rounded-sheet border border-rule bg-sheet p-4 shadow-(--lift)"
    >
      <h2 id="invite-heading" className="text-18 leading-tight font-bold">
        Invite someone
      </h2>
      <p className="mt-1 text-ink-2">
        They sign in with Google, then choose a PIN. Only invited people can sign in.
      </p>
      <form
        noValidate
        className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1.4fr)_auto] lg:items-start"
        onSubmit={(event) => {
          event.preventDefault();
          const found = validateInvite(values);
          setProblems(found);
          if (found.email) email.current?.focus();
          else if (found.facility) facility.current?.focus();
          else setAsking(true);
        }}
      >
        <Field id="invite-email" label="Email" error={problems.email}>
          {(props) => (
            <input
              {...props}
              ref={email}
              type="email"
              autoComplete="off"
              value={values.email}
              onChange={(event) => {
                change({ email: event.target.value });
              }}
              className={INPUT}
            />
          )}
        </Field>
        <Field id="invite-role" label="Role" error={undefined}>
          {(props) => (
            <select
              {...props}
              value={values.role}
              onChange={(event) => {
                change({ role: event.target.value as InviteValues["role"] });
              }}
              className={INPUT}
            >
              {ROLES.map((role) => (
                <option key={role} value={role}>
                  {roleLabel(role)}
                </option>
              ))}
            </select>
          )}
        </Field>
        {values.role === "admin" ? (
          <p className="self-end pb-2 text-ink-2">An admin belongs to no facility.</p>
        ) : (
          <Field id="invite-facility" label="Facility" error={problems.facility}>
            {(props) => (
              <select
                {...props}
                ref={facility}
                value={values.facility}
                onChange={(event) => {
                  change({ facility: event.target.value });
                }}
                className={INPUT}
              >
                <option value="">Choose a facility</option>
                {facilities.map((f) => (
                  <option key={f.key} value={f.key}>
                    {f.name}
                  </option>
                ))}
              </select>
            )}
          </Field>
        )}
        <div className="sm:col-span-2 lg:col-span-1 lg:pt-[1.625rem]">
          <Button ref={submit} type="submit" variant="primary" className="max-sm:w-full">
            Invite
          </Button>
        </div>
      </form>
      <PinDialog
        open={asking}
        onCancel={() => {
          setAsking(false);
        }}
        words={inviteWords(asked, roleLabel(values.role).toLowerCase(), facilityName)}
        request={request}
        persona={false}
        failureWords={inviteFailureWords}
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          const target = { email, facility, invite: submit }[landing.current];
          target.current?.focus();
          landing.current = "invite";
        }}
      />
    </section>
  );
}
