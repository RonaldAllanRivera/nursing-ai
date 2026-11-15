import { Link, Navigate, Outlet, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { AidLine } from "../components/AidLine";
import { Icon } from "../components/Icon";
import { Button } from "../components/ui/Button";
import { roleLabel } from "../session/personas";
import { useSession, useSignOut } from "../session/session";
import { applyTheme, readTheme, saveTheme, type Theme } from "../theme/theme";
import { ShiftControl } from "./ShiftControl";

const NAV_LINK =
  "inline-flex min-h-11 items-center rounded-full px-3 font-semibold text-ink [&.active]:bg-sunk [&.active]:underline [&.active]:underline-offset-4 hover:bg-sunk";

function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(readTheme);
  const night = theme === "night";
  return (
    <button
      type="button"
      aria-pressed={night}
      onClick={() => {
        const next: Theme = night ? "day" : "night";
        setTheme(next);
        saveTheme(next);
        applyTheme(next);
      }}
      className="inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-full border border-rule-strong bg-transparent px-4 font-semibold hover:bg-sunk aria-pressed:border-pen aria-pressed:bg-pen-tint aria-pressed:text-pen"
    >
      <Icon name="moon" />
      Night theme
    </button>
  );
}

/** Every signed-in screen: who is signed in, the nurse's shift, the theme, Sign out, then the page. */
export function Shell() {
  const { data: session } = useSession();
  const signOut = useSignOut();
  const navigate = useNavigate();

  // No session (signed out, or a request came back 401): the sign-in screen.
  if (session === null) return <Navigate to="/sign-in" />;
  if (session === undefined) return null;

  const isAdmin = session.facility_key === null;

  return (
    <>
      <header className="border-b border-rule bg-sheet">
        <div className="mx-auto flex max-w-[1280px] flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 sm:px-6">
          <div className="flex min-w-0 items-center gap-3">
            <div
              aria-hidden="true"
              className="grid size-12 flex-none place-items-center rounded-control rounded-bl-[2px] bg-primary font-bold text-primary-ink"
            >
              {session.initials}
            </div>
            <div className="min-w-0">
              <p className="flex flex-wrap items-baseline gap-x-3 text-18 leading-tight font-bold">
                <span>{session.display_name}</span>
                <span className="rounded-full border border-rule-strong px-2 text-14 font-semibold text-ink-2">
                  {roleLabel(session.role)}
                </span>
              </p>
            </div>
          </div>
          {session.shift && session.facility_key !== null ? (
            <ShiftControl shift={session.shift} facilityKey={session.facility_key} />
          ) : null}
          <nav aria-label="Main" className="ml-auto flex items-center gap-1">
            {isAdmin ? (
              <Link to="/settings" className={NAV_LINK}>
                Settings
              </Link>
            ) : (
              <Link to="/patients" className={NAV_LINK}>
                Patients
              </Link>
            )}
          </nav>
          <div className="flex items-center gap-2">
            <ThemeToggle />
            <Button
              disabled={signOut.isPending}
              onClick={() => {
                signOut.mutate(undefined, {
                  onSuccess: () => void navigate({ to: "/sign-in" }),
                });
              }}
            >
              Sign out
            </Button>
          </div>
        </div>
      </header>
      <AidLine />
      <main className="mx-auto max-w-[1280px] px-4 pt-2 pb-12 sm:px-6">
        <Outlet />
      </main>
    </>
  );
}
