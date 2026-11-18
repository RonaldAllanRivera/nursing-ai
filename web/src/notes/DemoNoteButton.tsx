import { useState } from "react";
import { Button } from "../components/ui/Button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "../components/ui/Dialog";

/**
 * "Use the demo note": a secondary button that hands the demo case's rough note to the box. When
 * she has typed something, it asks before replacing it (never silently). It never saves.
 * `putInBox` puts the words in the box; `focusBox` puts the cursor there afterwards.
 */
export function DemoNoteButton({
  hasTyped,
  disabled,
  putInBox,
  focusBox,
}: {
  hasTyped: boolean;
  disabled: boolean;
  putInBox: () => void;
  focusBox: () => void;
}) {
  const [asking, setAsking] = useState(false);
  return (
    <>
      <Button
        disabled={disabled}
        onClick={() => {
          if (hasTyped) {
            setAsking(true);
            return;
          }
          putInBox();
          focusBox();
        }}
      >
        Use the demo note
      </Button>
      <Dialog open={asking} onOpenChange={setAsking}>
        <DialogContent
          onOpenAutoFocus={(event) => {
            // The safe choice takes the first focus: an Enter held down on the opener replaces nothing.
            event.preventDefault();
            document.getElementById("demo-note-keep")?.focus();
          }}
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            focusBox();
          }}
        >
          <DialogTitle>Replace what you typed?</DialogTitle>
          <DialogDescription>
            The demo note will take the place of your note in the box. Nothing is saved until you
            choose Save note.
          </DialogDescription>
          <div className="mt-4 flex flex-wrap gap-3">
            <Button
              variant="primary"
              onClick={() => {
                putInBox();
                setAsking(false);
              }}
            >
              Replace my note
            </Button>
            <Button
              id="demo-note-keep"
              onClick={() => {
                setAsking(false);
              }}
            >
              Keep my note
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
