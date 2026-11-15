import { useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Icon } from "../components/Icon";
import { Button } from "../components/ui/Button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "../components/ui/Dialog";
import { Skeleton } from "../components/ui/Skeleton";
import { facilityListQuery } from "./facilities";
import { FacilityForm } from "./FacilityForm";
import { INPUT, LABEL } from "./fields";

/** The admin's one screen: pick a facility, edit its region profile, save. */
export function SettingsPage() {
  const list = useQuery(facilityListQuery);
  const [chosen, setChosen] = useState<string | null>(null);
  const [asked, setAsked] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const keep = useRef<HTMLButtonElement>(null);

  const facilities = list.data ?? [];
  const key = chosen ?? facilities[0]?.profile.key ?? null;
  const current = facilities.find((f) => f.profile.key === key);

  const switchTo = (next: string) => {
    if (next === key) return;
    if (dirty) {
      setAsked(next);
      return;
    }
    setChosen(next);
  };

  return (
    <section aria-labelledby="settings-heading">
      <h1 id="settings-heading" className="text-24 leading-tight font-bold">
        Settings
      </h1>
      <p className="mt-1 text-ink-2">
        Changes apply to new notes. Notes already written keep their shift.
      </p>

      {list.isError && !list.data ? (
        <p role="alert" className="mt-4 flex items-start gap-2 text-stop">
          <Icon name="flag" className="mt-0.5" />
          The facilities did not load. Reload the page to try again.
        </p>
      ) : !list.data ? (
        <div aria-busy="true" className="mt-4 grid gap-3">
          <span className="sr-only">Loading the facilities…</span>
          <Skeleton className="h-12 max-w-md" />
          <Skeleton className="h-40" />
        </div>
      ) : facilities.length === 0 ? (
        <p className="mt-4 text-ink-2">
          No facilities are set up yet. Add one on the server, then reload this page.
        </p>
      ) : (
        <>
          <div className="mt-4 max-w-md">
            <label htmlFor="facility-picker" className={LABEL}>
              Facility
            </label>
            <select
              id="facility-picker"
              value={key ?? ""}
              onChange={(event) => {
                switchTo(event.target.value);
              }}
              className={INPUT}
            >
              {facilities.map((facility) => (
                <option key={facility.profile.key} value={facility.profile.key}>
                  {facility.profile.name}
                </option>
              ))}
            </select>
          </div>
          {key ? <FacilityForm key={key} facilityKey={key} onDirtyChange={setDirty} /> : null}
        </>
      )}

      <Dialog
        open={asked !== null}
        onOpenChange={(open) => {
          if (!open) setAsked(null);
        }}
      >
        <DialogContent
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            keep.current?.focus();
          }}
        >
          <DialogTitle>Discard your changes?</DialogTitle>
          <DialogDescription>
            {current
              ? `Your changes to ${current.profile.name} are not saved.`
              : "Your changes are not saved."}{" "}
            Switching facility drops them.
          </DialogDescription>
          <div className="mt-4 flex flex-wrap gap-3">
            <Button
              ref={keep}
              variant="primary"
              onClick={() => {
                setAsked(null);
              }}
            >
              Keep editing
            </Button>
            <Button
              className="border-stop text-stop"
              onClick={() => {
                setChosen(asked);
                setDirty(false);
                setAsked(null);
              }}
            >
              Discard changes
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </section>
  );
}
