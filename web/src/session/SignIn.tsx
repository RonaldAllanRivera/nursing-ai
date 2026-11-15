import { useNavigate } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { AidLine } from "../components/AidLine";
import { Skeleton } from "../components/ui/Skeleton";
import { HealthStatus } from "../health/HealthStatus";
import { groupPersonas, personaLabel } from "./personas";
import { personasQuery, useSignIn } from "./session";

/** The sign-in sheet: ruled paper, one group per facility, the role first on every button. */
export function SignIn() {
  const personas = useQuery(personasQuery);
  const signIn = useSignIn();
  const navigate = useNavigate();

  return (
    <>
      <AidLine />
      <main className="mx-auto max-w-2xl px-4 pt-4 pb-12 sm:px-6">
        <p className="text-14 font-semibold text-ink-2">Sourceline</p>
        <h1 className="mt-1 text-24 leading-tight font-bold">Sign in</h1>
        <p className="mt-1 text-ink-2">
          Choose who you are signing in as. Everything here is made-up demo data.
        </p>

        <div
          className="mt-4 rounded-sheet border border-rule bg-sheet px-4 py-3 shadow-(--lift) sm:px-6"
          style={{
            backgroundImage:
              "repeating-linear-gradient(to bottom, transparent 0, transparent calc(var(--lh-note) - 1px), var(--ruled) calc(var(--lh-note) - 1px), var(--ruled) var(--lh-note))",
            backgroundPositionY: "var(--sp-3)",
          }}
        >
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

        <div className="mt-8 text-14 text-ink-2">
          <HealthStatus />
        </div>
      </main>
    </>
  );
}
