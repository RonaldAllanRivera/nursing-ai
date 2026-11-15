import { afterEach, describe, expect, it, vi } from "vitest";
import { createKeyKeeper, newIdempotencyKey } from "./idempotency";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("newIdempotencyKey", () => {
  it("newIdempotencyKey uses getRandomValues and makes a UUID v4", () => {
    const spy = vi.spyOn(globalThis.crypto, "getRandomValues");
    const key = newIdempotencyKey();
    expect(spy).toHaveBeenCalled();
    expect(key).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  });

  it("makes a different key each time", () => {
    expect(newIdempotencyKey()).not.toBe(newIdempotencyKey());
  });
});

describe("createKeyKeeper", () => {
  const counter = () => {
    let n = 0;
    return () => `key-${String(++n)}`;
  };

  it("makes the key on the first save, not before", () => {
    const make = vi.fn(counter());
    const keeper = createKeyKeeper(make);
    expect(make).not.toHaveBeenCalled();
    expect(keeper.keyFor("pt c/o hilo")).toBe("key-1");
  });

  it("keeps the key for the same text (an automatic retry or Try again)", () => {
    const keeper = createKeyKeeper(counter());
    expect(keeper.keyFor("pt c/o hilo")).toBe("key-1");
    expect(keeper.keyFor("pt c/o hilo")).toBe("key-1");
  });

  it("makes a new key when the text changes after a failure", () => {
    const keeper = createKeyKeeper(counter());
    expect(keeper.keyFor("pt c/o hilo")).toBe("key-1");
    expect(keeper.keyFor("pt c/o hilo since 2am")).toBe("key-2");
    expect(keeper.keyFor("pt c/o hilo since 2am")).toBe("key-2");
  });

  it("ends the key after a successful send", () => {
    const keeper = createKeyKeeper(counter());
    expect(keeper.keyFor("pt c/o hilo")).toBe("key-1");
    keeper.done();
    expect(keeper.keyFor("pt c/o hilo")).toBe("key-2");
  });
});
