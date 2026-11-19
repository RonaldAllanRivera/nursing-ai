import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { MockOptions } from "../mocks/options";
import { renderApp } from "./render";

/** The PIN every demo person shares (the sign-in options hand it out). */
export const DEMO_PIN = "135790";

/**
 * Finds the "Demo PIN: 135790" hint by all its words: its digits are set in the note font, so
 * they are an element of their own and a plain text match would not see the whole line.
 */
export const demoPinHint =
  (pin: string = DEMO_PIN) =>
  (_content: string, element: Element | null) =>
    element?.tagName === "P" && element.textContent === `Demo PIN: ${pin}`;

/** Types a PIN into the PIN screen that is showing and presses Enter. */
export async function typePin(pin: string = DEMO_PIN, label = "PIN") {
  await userEvent.type(await screen.findByLabelText(label), `${pin}{Enter}`);
}

/**
 * On the sign-in screen: choose this person (the button's name) and enter the demo PIN, the way a
 * visitor gets past the PIN screen every sign-in now ends at.
 */
export async function chooseAndUnlock(name: string) {
  await userEvent.click(await screen.findByRole("button", { name }));
  await typePin();
}

/** Mounts the app at the sign-in screen and signs this person in all the way through the PIN. */
export async function signInAsPersona(name: string, options: MockOptions = {}) {
  const view = await renderApp("/sign-in", options);
  await chooseAndUnlock(name);
  return view;
}
