import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Icon } from "../components/Icon";
import { Skeleton } from "../components/ui/Skeleton";
import { useSession } from "../session/session";
import { facilityListQuery } from "../settings/facilities";
import { InviteForm } from "./InviteForm";
import { canInvite, canSeeStaff, sortStaff } from "./permissions";
import { StaffActionDialog, type Acting } from "./StaffActionDialog";
import { StaffListRow } from "./StaffRow";
import { staffQuery } from "./staffApi";
import { lockedWords } from "./words";

const REFRESHED = "That didn't work. The list has been refreshed. Check it, then try again.";
const NOT_REFRESHED =
  "That didn't work, and the list did not refresh. Reload the page to try again.";

/** The admin's and head nurses' list of people: invite, end access, clear a locked PIN. */
export function StaffPage() {
  const { data: session } = useSession();
  const queryClient = useQueryClient();
  const staff = useQuery(staffQuery);
  const facilities = useQuery(facilityListQuery);
  const [acting, setActing] = useState<Acting | null>(null);
  const [open, setOpen] = useState(false);
  const [said, setSaid] = useState("");
  const [failed, setFailed] = useState<string | null>(null);

  if (!session || !canSeeStaff(session)) return null;
  const admin = canInvite(session);

  const nameOf = (key: string | null) =>
    key === null
      ? "All facilities"
      : (facilities.data?.find((f) => f.profile.key === key)?.profile.name ?? key);

  const done = (words: string) => {
    setFailed(null);
    setSaid(words);
  };
  // The person is gone or the action is no longer allowed: the list was out of date. Look at it
  // again, and say so only once it has been.
  const stale = async () => {
    setSaid("");
    setFailed(null);
    await queryClient.invalidateQueries({ queryKey: staffQuery.queryKey });
    const state = queryClient.getQueryState(staffQuery.queryKey);
    setFailed(state?.status === "error" ? NOT_REFRESHED : REFRESHED);
  };
  const rows = staff.data ? sortStaff(staff.data) : [];
  const locked = rows.filter((r) => r.status === "active" && r.pin_locked).length;

  return (
    <section aria-labelledby="staff-heading">
      <h1 id="staff-heading" className="text-24 leading-tight font-bold">
        Staff
      </h1>
      <p className="mt-1 text-ink-2">
        {admin
          ? "Invite people, end someone's access, or clear a locked PIN."
          : "The people at your facility. Clear a PIN when someone is locked out."}
      </p>

      {/* What the last action did, read aloud; always in the page so the first one is announced. */}
      <p role="status" className="mt-2 flex items-start gap-2 empty:hidden">
        {said ? (
          <>
            <Icon name="check" className="mt-0.5 text-ok" />
            <span>{said}</span>
          </>
        ) : null}
      </p>
      {failed !== null ? (
        <p role="alert" className="mt-2 flex items-start gap-2 text-stop">
          <Icon name="flag" className="mt-0.5" />
          <span>{failed}</span>
        </p>
      ) : null}

      {admin ? (
        <InviteForm
          facilities={(facilities.data ?? []).map((f) => ({
            key: f.profile.key,
            name: f.profile.name,
          }))}
          onDone={done}
          onStale={() => void stale()}
        />
      ) : null}

      <div className="mt-4 overflow-hidden rounded-sheet border border-rule bg-sheet shadow-(--lift)">
        {staff.isPending ? (
          <div aria-busy="true" className="grid gap-px p-3">
            <span className="sr-only">Loading the staff…</span>
            <Skeleton className="h-14" />
            <Skeleton className="h-14" />
            <Skeleton className="h-14" />
          </div>
        ) : staff.isError && !staff.data ? (
          <p role="alert" className="flex items-start gap-2 p-4 text-stop">
            <Icon name="flag" className="mt-0.5" />
            <span>The staff list did not load. Reload the page to try again.</span>
          </p>
        ) : rows.length === 0 ? (
          <p className="p-4 text-ink-2">
            {admin
              ? "No one is on the list yet. Invite someone above."
              : "No one else is on the list for your facility yet. The admin invites people."}
          </p>
        ) : (
          <>
            {locked > 0 ? (
              <p className="flex items-center gap-2 border-b border-rule bg-review-tint px-3 py-2 font-semibold text-review">
                <Icon name="lock" />
                <span>{lockedWords(locked)}</span>
              </p>
            ) : null}
            <ul aria-label="Staff" className="m-0 list-none p-0">
              {rows.map((row) => (
                <StaffListRow
                  key={row.id}
                  row={row}
                  actor={session}
                  facilityName={nameOf(row.facility_key)}
                  onAct={(action, picked, opener) => {
                    setSaid("");
                    setFailed(null);
                    setActing({ action, row: picked, opener });
                    setOpen(true);
                  }}
                />
              ))}
            </ul>
          </>
        )}
      </div>

      <StaffActionDialog
        acting={acting}
        open={open}
        onClose={() => {
          setOpen(false);
        }}
        onDone={done}
        onStale={() => void stale()}
      />
    </section>
  );
}
