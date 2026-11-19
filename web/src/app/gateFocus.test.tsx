import { render, screen } from "@testing-library/react";
import { useRef } from "react";
import { describe, expect, it } from "vitest";
import { GATE_ATTRIBUTE, useRestoreFocusAfterGate } from "./gateFocus";

function Page({ gateUp, scope }: { gateUp: boolean; scope: string }) {
  const page = useRef<HTMLElement>(null);
  useRestoreFocusAfterGate(gateUp, page, scope);
  return (
    <main ref={page} tabIndex={-1} aria-label="page">
      {gateUp ? (
        <section {...{ [GATE_ATTRIBUTE]: "" }}>
          <input aria-label="pin" id="unlock-pin" />
        </section>
      ) : (
        <>
          <textarea aria-label="note" id="rough-note" />
          <button>Save</button>
        </>
      )}
    </main>
  );
}

describe("restoring the cursor after a gate", () => {
  it("puts it back on the element that had it", () => {
    const view = render(<Page gateUp={false} scope="/patients/a" />);
    screen.getByLabelText("note").focus();
    view.rerender(<Page gateUp scope="/patients/a" />);
    screen.getByLabelText("pin").focus();
    view.rerender(<Page gateUp={false} scope="/patients/a" />);
    expect(screen.getByLabelText("note")).toHaveFocus();
  });

  it("forgets an id once the focus has moved to an element without one", () => {
    const view = render(<Page gateUp={false} scope="/patients/a" />);
    screen.getByLabelText("note").focus();
    screen.getByRole("button", { name: "Save" }).focus();
    view.rerender(<Page gateUp scope="/patients/a" />);
    screen.getByLabelText("pin").focus();
    view.rerender(<Page gateUp={false} scope="/patients/a" />);
    expect(screen.getByRole("main")).toHaveFocus();
  });

  it("does not hand another page's focus to a page with the same ids", () => {
    const view = render(<Page gateUp={false} scope="/patients/a" />);
    screen.getByLabelText("note").focus();
    // She went to another patient (the same ids), and the gate came up there.
    view.rerender(<Page gateUp={false} scope="/patients/b" />);
    view.rerender(<Page gateUp scope="/patients/b" />);
    screen.getByLabelText("pin").focus();
    view.rerender(<Page gateUp={false} scope="/patients/b" />);
    expect(screen.getByRole("main")).toHaveFocus();
  });
});
