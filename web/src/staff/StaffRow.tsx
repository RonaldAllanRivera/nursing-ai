import { Icon, type IconName } from "../components/Icon";
import { Button } from "../components/ui/Button";
import { cn } from "../lib/cn";
import { roleLabel } from "../session/personas";
import { canResetPin, canRevoke, type StaffActor } from "./permissions";
import type { StaffAction, StaffRow as Row } from "./staffApi";

const STATUS: Record<Row["status"], { icon: IconName; words: string; tone: string }> = {
  active: { icon: "check", words: "Active", tone: "text-ok" },
  invited: { icon: "box", words: "Invited", tone: "text-ink-2" },
  revoked: { icon: "removed", words: "Revoked", tone: "text-ink-2" },
};

/**
 * One person on the list: name (their email says who an invited person is until they sign in),
 * role and facility, status in an icon and words, and only the actions the actor may take.
 * A revoked row stays but is quieter.
 */
export function StaffListRow({
  row,
  actor,
  facilityName,
  onAct,
}: {
  row: Row;
  actor: StaffActor;
  facilityName: string;
  onAct: (action: StaffAction, row: Row, opener: HTMLElement) => void;
}) {
  const status = STATUS[row.status];
  const locked = row.status === "active" && row.pin_locked;
  return (
    <li
      id={`staff-row-${row.id}`}
      tabIndex={-1}
      className={cn(
        "grid gap-x-4 gap-y-2 border-b border-ruled px-3 py-3 focus-visible:outline-3 focus-visible:-outline-offset-3 focus-visible:outline-pen last:border-b-0 sm:grid-cols-2 sm:items-center lg:grid-cols-[minmax(0,1fr)_14rem_14rem_14rem]",
        row.status === "revoked" && "bg-sunk text-ink-2",
      )}
    >
      <div className="min-w-0">
        <p
          className={cn(
            "text-18 leading-tight font-bold",
            row.status === "revoked" && "font-semibold",
          )}
        >
          {row.display_name}
        </p>
        {row.email !== row.display_name ? (
          <p className="text-14 break-words text-ink-2">{row.email}</p>
        ) : null}
      </div>
      <p className="text-ink-2">
        <span>{roleLabel(row.role)}</span>
        <span className="block text-14">{facilityName}</span>
      </p>
      <p className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className={cn("inline-flex items-center gap-1 font-semibold", status.tone)}>
          <Icon name={status.icon} />
          <span>{status.words}</span>
        </span>
        {locked ? (
          <span className="inline-flex items-center gap-1 rounded-full border border-review bg-review-tint px-2 font-semibold text-review">
            <Icon name="lock" />
            <span>PIN locked</span>
          </span>
        ) : null}
      </p>
      <div className="flex flex-wrap gap-2 lg:justify-end">
        {canResetPin(actor, row) ? (
          <Button
            aria-label={`Reset PIN for ${row.display_name}`}
            onClick={(event) => {
              onAct("reset", row, event.currentTarget);
            }}
          >
            Reset PIN
          </Button>
        ) : null}
        {canRevoke(actor, row) ? (
          <Button
            className="border-stop text-stop"
            aria-label={`Revoke ${row.display_name}'s access`}
            onClick={(event) => {
              onAct("revoke", row, event.currentTarget);
            }}
          >
            Revoke
          </Button>
        ) : null}
      </div>
    </li>
  );
}
