import { useState } from "react";
import { Icon } from "../components/Icon";
import { failureOf, useReloadNote } from "./writes";

/** Why a write was refused, and what to do next. A stale or locked note offers Reload note. */
export function WriteProblem({
  error,
  withText = false,
  noteId,
  onReloaded,
}: {
  error: unknown;
  /** The nurse has typed something that is still on screen. */
  withText?: boolean;
  noteId: string;
  onReloaded: () => void;
}) {
  const reload = useReloadNote(noteId);
  const [reloading, setReloading] = useState(false);
  const failure = failureOf(error);
  const needsReload = failure.kind === "stale" || failure.kind === "locked";
  return (
    <div role="alert" className="write-problem">
      <p>
        <Icon name="flag" />
        {failure.kind === "stale" ? (
          <span>
            {withText
              ? "This note changed somewhere else. Reload to see the latest version. Your text is still here."
              : "This note changed somewhere else. Reload to see the latest version."}
          </span>
        ) : failure.kind === "locked" ? (
          <>
            <span>This note is locked.</span> <span>Reload to see it.</span>
          </>
        ) : failure.kind === "incomplete" ? (
          <span>Some lines still need a check. Cancel, then look at each flagged line.</span>
        ) : (
          <span>That change was not saved. Check your connection and try again.</span>
        )}
      </p>
      {needsReload ? (
        <button
          type="button"
          className="btn"
          aria-disabled={reloading || undefined}
          onClick={() => {
            if (reloading) return;
            setReloading(true);
            void reload(onReloaded).finally(() => {
              setReloading(false);
            });
          }}
        >
          {reloading ? "Reloading…" : "Reload note"}
        </button>
      ) : null}
    </div>
  );
}
