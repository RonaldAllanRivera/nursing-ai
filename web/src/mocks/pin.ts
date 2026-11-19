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

/**
 * The server's own words on `body.pin`, as it answers them: a PIN that breaks the six-digit pattern
 * fails its request schema ("invalid value"), and a weak new PIN is "that PIN is too easy". The
 * screens never show these; they say it in their own words.
 */
export const PIN_FORMAT_MESSAGE = "invalid value";
export const PIN_WEAK_MESSAGE = "that PIN is too easy";
