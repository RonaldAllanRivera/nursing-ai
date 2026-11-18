import { useRef, useState } from "react";
import type { components } from "../api/schema";
import { ApiError } from "../api/errors";
import { Button } from "../components/ui/Button";
import { isPinRefusal } from "../session/pin";
import { roleLabel } from "../session/personas";
import { Field, INPUT } from "../settings/fields";
import { PinDialog } from "../settings/PinDialog";
import {
  EMAIL_PROBLEM,
  EMAIL_TAKEN,
  validateInvite,
  type InviteProblems,
  type InviteValues,
} from "./invite";
import { useInvite } from "./staffApi";
import { DONE, inviteWords } from "./words";

const ROLES: components["schemas"]["Role"][] = ["staff_nurse", "head_nurse", "admin"];
const EMPTY: InviteValues = { email: "", role: "staff_nurse", facility: "" };

/** What a refused invitation says about the form, when it is about the form (else `null`). */
function problemsFrom(error: unknown): InviteProblems | null {
  if (!(error instanceof ApiError)) return null;
  if (error.status === 409 && error.problem?.code === "email_taken") return { email: EMAIL_TAKEN };
  if (error.status !== 422) return null;
  const found: InviteProblems = {};
  for (const field of error.problem?.errors ?? []) {
    if (field.field === "body.email") found.email = field.message;
    if (field.field === "body.facility_key") found.facility = field.message;
  }
  return found.email || found.facility ? found : { email: EMAIL_PROBLEM };
}

/**
 * The admin's invitation: email, role, facility (nurses only). The form is checked before the PIN
 * is asked for. A taken email is said under the email field, with what was typed kept.
 */
export function InviteForm({
  facilities,
  onDone,
  onFailed,
}: {
  facilities: { key: string; name: string }[];
  onDone: (words: string) => void;
  onFailed: (error: unknown) => void;
}) {
  const [values, setValues] = useState<InviteValues>(EMPTY);
  const [problems, setProblems] = useState<InviteProblems>({});
  const [asking, setAsking] = useState(false);
  const email = useRef<HTMLInputElement>(null);
  const facility = useRef<HTMLSelectElement>(null);
  const submit = useRef<HTMLButtonElement>(null);
  const landing = useRef<"email" | "invite">("invite");

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
      if (isPinRefusal(error)) return;
      landing.current = "email";
      setAsking(false);
      const about = problemsFrom(error);
      if (about) setProblems(about);
      else onFailed(error);
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
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          (landing.current === "email" ? email : submit).current?.focus();
          landing.current = "invite";
        }}
      />
    </section>
  );
}
