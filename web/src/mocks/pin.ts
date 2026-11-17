/** The PIN every demo persona shares (the sign-in options hand it out while the demo is on). */
export const DEMO_PIN = "135790";

/** A PIN is exactly six ASCII digits. */
export function isPinFormat(value: unknown): value is string {
  return typeof value === "string" && /^[0-9]{6}$/.test(value);
}

/** A new PIN may not be one digit repeated or a straight run up or down (123456, 654321). */
export function isWeakPin(pin: string): boolean {
  const digits = Array.from(pin, Number);
  const steps = digits.slice(1).map((d, i) => d - (digits[i] ?? 0));
  return steps.every((s) => s === 0) || steps.every((s) => s === 1) || steps.every((s) => s === -1);
}

export const PIN_FORMAT_MESSAGE = "A PIN is 6 digits, 0 to 9.";
export const PIN_WEAK_MESSAGE = "Choose a PIN that isn't one digit repeated or a run like 123456.";
