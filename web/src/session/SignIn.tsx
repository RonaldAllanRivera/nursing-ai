import { useNavigate, useSearch } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { AidLine } from "../components/AidLine";
import { Icon } from "../components/Icon";
import { Skeleton } from "../components/ui/Skeleton";
import { HealthStatus } from "../health/HealthStatus";
import { groupPersonas, personaLabel } from "./personas";
import { personasQuery, signInOptionsQuery, useSignIn } from "./session";
import { GOOGLE_START, SIGN_IN_MESSAGES, offeredFrom, signInErrorFrom } from "./signInOptions";

/** The sign-in screen: Google for invited staff, then the demo people on a ruled sheet, role first on every button. */
export function SignIn() {
  // The router keeps the address's other values next to the validated ones, so check again here.
  const error = signInErrorFrom(useSearch({ from: "/sign-in" }));
  const options = useQuery(signInOptionsQuery);
  const offered = offeredFrom(options.data);
  const personas = useQuery({ ...personasQuery, enabled: !options.isPending && offered.personas });
  const signIn = useSignIn();
  const navigate = useNavigate();
  // Choosing a way in answers the refusal, so it goes (the Google link then leaves the page).
  const clearError = () => void navigate({ to: "/sign-in", search: {}, replace: true });

  return (
    <>
      <AidLine />
      <main className="mx-auto max-w-2xl px-4 pt-4 pb-12 sm:px-6">
        <p className="text-14 font-semibold text-ink-2">Sourceline</p>
        <h1 className="mt-1 text-24 leading-tight font-bold">Sign in</h1>
        <p className="mt-1 text-ink-2">
          {offered.google
            ? "Invited staff sign in with Google."
            : "Choose who you are signing in as."}
          {offered.personas ? " Everything in the demo is made-up data." : ""}
        </p>

        {error ? (
          <p
            role="alert"
            className="mt-4 flex items-start gap-2 rounded-control border border-stop bg-stop-tint px-3 py-2 text-stop"
          >
            <Icon name="close" className="mt-0.5" />
            <span>{SIGN_IN_MESSAGES[error]}</span>
          </p>
        ) : null}

        {options.isPending ? (
          <div className="mt-4 grid gap-3" aria-busy="true">
            <span className="sr-only">Loading the ways to sign in…</span>
            <Skeleton className="h-11" />
            <Skeleton className="h-24" />
          </div>
        ) : (
          <>
            {offered.google ? (
              <a
                href={GOOGLE_START}
                onClick={error ? clearError : undefined}
                className="mt-4 inline-flex min-h-11 w-full items-center justify-center rounded-full border border-transparent bg-primary px-4 font-ui font-semibold text-primary-ink hover:opacity-90 sm:w-auto"
              >
                Sign in with Google
              </a>
            ) : null}

            {offered.personas ? (
              <div
                className="mt-4 rounded-sheet border border-rule bg-sheet px-4 py-3 shadow-(--lift) sm:px-6"
                style={{
                  backgroundImage:
                    "repeating-linear-gradient(to bottom, transparent 0, transparent calc(var(--lh-note) - 1px), var(--ruled) calc(var(--lh-note) - 1px), var(--ruled) var(--lh-note))",
                  backgroundPositionY: "var(--sp-3)",
                }}
              >
                {offered.google ? <h2 className="text-18 font-bold">Try the demo</h2> : null}
                {offered.demoPin ? (
                  // Its own paper patch, so a ruled line never runs through the digits.
                  <p className="mt-1 mb-3 inline-block rounded-control border border-rule-strong bg-sheet px-2 py-0.5 font-note text-ink">{`Demo PIN: ${offered.demoPin}`}</p>
                ) : null}
                {personas.isPending ? (
                  <div className="grid gap-3" aria-busy="true">
                    <span className="sr-only">Loading the people you can sign in as…</span>
                    <Skeleton className="h-6 w-1/2" />
                    <Skeleton className="h-11" />
                    <Skeleton className="h-11" />
                  </div>
                ) : personas.isError && !personas.data ? (
                  <p role="alert" className="text-stop">
                    The list of people did not load. Reload the page to try again.
                  </p>
                ) : (
                  <div className="grid gap-4">
                    {groupPersonas(personas.data).map((group) => (
                      <fieldset key={group.heading} className="m-0 min-w-0 border-0 p-0">
                        <legend className="mb-2 p-0 text-18 font-bold">{group.heading}</legend>
                        <div className="grid gap-2">
                          {group.personas.map((persona) => (
                            <button
                              key={persona.id}
                              type="button"
                              disabled={signIn.isPending}
                              onClick={() => {
                                if (error) clearError();
                                signIn.mutate(persona.id, {
                                  onSuccess: () => void navigate({ to: "/" }),
                                });
                              }}
                              className="flex min-h-11 w-full cursor-pointer items-center gap-3 rounded-control rounded-bl-[2px] border border-rule-strong bg-sheet px-3 py-1 text-left font-semibold hover:bg-sunk disabled:cursor-not-allowed disabled:opacity-60"
                            >
                              <span
                                aria-hidden="true"
                                className="grid size-8 flex-none place-items-center rounded-control bg-primary text-14 font-bold text-primary-ink"
                              >
                                {persona.initials}
                              </span>
                              <span>{personaLabel(persona)}</span>
                            </button>
                          ))}
                        </div>
                      </fieldset>
                    ))}
                  </div>
                )}
                {signIn.isError ? (
                  <p role="alert" className="mt-3 text-stop">
                    Signing in did not work. Choose the person again.
                  </p>
                ) : null}
              </div>
            ) : null}

            {!offered.google && !offered.personas ? (
              <p className="mt-4 text-ink-2">Signing in is not open here yet.</p>
            ) : null}
          </>
        )}

        <div className="mt-8 text-14 text-ink-2">
          <HealthStatus />
        </div>
      </main>
    </>
  );
}
