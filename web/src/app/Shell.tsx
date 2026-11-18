import { Link, Navigate, Outlet, useNavigate, useRouterState } from "@tanstack/react-router";
import { useRef, useState } from "react";
import { AidLine } from "../components/AidLine";
import { Icon } from "../components/Icon";
import { Button } from "../components/ui/Button";
import { GateScreen } from "../session/GateScreen";
import { roleLabel } from "../session/personas";
import { screenForGate } from "../session/pin";
import { useSession, useSignOut } from "../session/session";
import { applyTheme, readTheme, saveTheme, type Theme } from "../theme/theme";
import { canSeeStaff } from "../staff/permissions";
import { useFacility } from "../facility/useFacility";
import { useIdleLock, useLookAgainWhenSeen } from "../session/useIdleLock";
import { useSessionExpiry } from "../session/useSessionExpiry";
import { useRestoreFocusAfterGate } from "./gateFocus";
import { ShellFrame } from "./RouteScreens";
import { ShiftControl } from "./ShiftControl";

const NAV_LINK =
  "inline-flex min-h-11 items-center rounded-full px-2 font-semibold sm:px-3 text-ink [&.active]:bg-sunk [&.active]:underline [&.active]:underline-offset-4 hover:bg-sunk";

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
      className="inline-flex min-h-11 min-w-11 cursor-pointer items-center justify-center gap-2 rounded-full border border-rule-strong bg-transparent font-semibold hover:bg-sunk max-sm:px-0 sm:px-4 aria-pressed:border-pen aria-pressed:bg-pen-tint aria-pressed:text-pen"
    >
      <Icon name="moon" />
      <span className="max-sm:sr-only">Night theme</span>
    </button>
  );
}

/** Every signed-in screen: who is signed in, the nurse's shift, the theme, Sign out, then the page. */
export function Shell() {
  const { data: session } = useSession();
  const signOut = useSignOut();
  const navigate = useNavigate();
  const page = useRef<HTMLElement>(null);
  const gateUp = session ? screenForGate(session.gate) !== null : false;
  const where = useRouterState({ select: (state) => state.location.pathname });
  useRestoreFocusAfterGate(gateUp, page, where);
  // The browser's own timers: an unattended screen locks, a session past its hours ends, and a
  // tab seen again asks who the session is now. The facility stays loaded here so the hours a
  // session lasts are known even while a gate hides the shift picker.
  useFacility(session?.facility_key ?? null);
  useIdleLock(session);
  useSessionExpiry(session?.expires_at);
  useLookAgainWhenSeen(session != null);

  // No session (signed out, or a request came back 401): the sign-in screen.
  if (session === null) return <Navigate to="/sign-in" />;
  if (session === undefined) return null;

  const isAdmin = session.facility_key === null;
  const endSession = () => {
    signOut.mutate(undefined, {
      onSuccess: () => void navigate({ to: "/sign-in" }),
    });
  };

  return (
    <>
      <header className="border-b border-rule bg-sheet">
        <div className="mx-auto flex max-w-[1280px] flex-wrap items-center gap-x-2 gap-y-2 px-4 py-3 sm:gap-x-4 sm:px-6">
          <div className="flex min-w-0 flex-[1_1_14rem] items-center gap-3 sm:flex-none">
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
          {/* On a phone, Sign out sits on the first row beside who is signed in, so it comes second
              in the DOM and the focus order follows what the eye sees. From `sm` up everything fits
              on one row and Sign out goes last. While a gate is up the page is hidden, so the shift
              picker and the links (which lead only to hidden pages) go too, and the one way out is
              "Not you? Switch nurse": the same action, in the words of someone at the wrong screen. */}
          {gateUp ? (
            <>
              <div className="flex items-center gap-2 sm:order-last">
                <p className="text-14 text-ink-2">Not you?</p>
                <Button disabled={signOut.isPending} onClick={endSession}>
                  Switch nurse
                </Button>
              </div>
              <div aria-hidden="true" className="max-sm:hidden sm:ml-auto" />
            </>
          ) : (
            <>
              <Button className="sm:order-last" disabled={signOut.isPending} onClick={endSession}>
                Sign out
              </Button>
              {session.shift && session.facility_key !== null ? (
                <ShiftControl shift={session.shift} facilityKey={session.facility_key} />
              ) : null}
              <nav aria-label="Main" className="flex items-center gap-1 sm:ml-auto">
                {isAdmin ? (
                  <Link to="/settings" className={NAV_LINK}>
                    Settings
                  </Link>
                ) : (
                  <Link to="/patients" className={NAV_LINK}>
                    Patients
                  </Link>
                )}
                {canSeeStaff(session) ? (
                  <Link to="/staff" className={NAV_LINK}>
                    Staff
                  </Link>
                ) : null}
              </nav>
            </>
          )}
          <ThemeToggle />
          {signOut.isError ? (
            <p role="alert" className="order-last basis-full text-14 text-stop">
              Signing out did not work. Try again.
            </p>
          ) : null}
        </div>
      </header>
      <AidLine />
      <main
        ref={page}
        tabIndex={-1}
        className="mx-auto max-w-[1280px] px-4 pt-2 pb-12 outline-none sm:px-6"
      >
        {/* A gate replaces the page (same address, header stays): nothing of a patient is left in
            the page while someone has not proved who they are, and the page comes back as it was. */}
        {!gateUp ? (
          <ShellFrame.Provider value={true}>
            {/* Keyed by who is signed in: if the session turns out to be someone else's, the page starts again, with nothing typed by the last person. */}
            <Outlet key={session.user_id} />
          </ShellFrame.Provider>
        ) : (
          <GateScreen session={session} />
        )}
      </main>
    </>
  );
}
