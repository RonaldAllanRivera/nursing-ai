/**
 * A UUID v4 from `crypto.getRandomValues`. Never `crypto.randomUUID`: it only exists in secure
 * contexts, and the app is tested over LAN http.
 */
export function newIdempotencyKey(): string {
  const bytes = new Uint8Array(16);
  globalThis.crypto.getRandomValues(bytes);
  bytes[6] = ((bytes[6] ?? 0) & 0x0f) | 0x40; // version 4
  bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80; // variant 10xx
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/**
 * One key per typed note. Made on the first save, kept across retries and "Try again", replaced
 * only when the text changes after a send that did not succeed, and ended by a successful send.
 */
export function createKeyKeeper(make: () => string = newIdempotencyKey) {
  let current: { key: string; text: string } | null = null;
  return {
    keyFor(text: string): string {
      if (current?.text !== text) current = { key: make(), text };
      return current.key;
    },
    done(): void {
      current = null;
    },
  };
}
