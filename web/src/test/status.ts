import { screen } from "@testing-library/react";

/** The page's own status region: the app-wide "waking" line is a status too, and is not what a screen test means. */
export function pageStatus(): HTMLElement {
  const [region, ...others] = screen
    .getAllByRole("status")
    .filter((element) => element.id !== "waking-notice");
  if (!region || others.length > 0) throw new Error("Expected exactly one page status region.");
  return region;
}
