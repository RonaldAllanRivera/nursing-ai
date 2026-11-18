import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { demoPinHint } from "../test/signIn";
import { DemoPinChip } from "./DemoPin";

describe("the demo PIN hint", () => {
  it("reads as a hint above the field, not as a field filled in: no box like the PIN field's", () => {
    render(<DemoPinChip pin="135790" id="hint" />);
    const hint = screen.getByText(demoPinHint());
    expect(hint).toHaveAttribute("id", "hint");
    // The PIN field is a bordered, rounded box in the note font; the hint has no border or corners.
    expect(hint.className).not.toMatch(/(^|\s)(border|rounded-control)(\s|$)/);
    // The digits are the thing to copy: set in the note font, apart from the plain words.
    expect(screen.getByText("135790")).toHaveClass("font-note");
    expect(hint).not.toHaveClass("font-note");
  });
});
