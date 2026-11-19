import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import { createQueryClient } from "../app/queryClient";
import { clearPersonData } from "../session/session";
import { holdNote, readHeldNote } from "./heldNote";

describe("held note", () => {
  it("keeps the text per patient and nothing for an empty note", () => {
    const client = new QueryClient();
    holdNote(client, "p1", "pt c/o hilo");
    expect(readHeldNote(client, "p1")).toBe("pt c/o hilo");
    expect(readHeldNote(client, "p2")).toBe("");
    holdNote(client, "p1", "");
    expect(readHeldNote(client, "p1")).toBe("");
  });

  it("is never garbage-collected while nobody is looking, however long a gate lasts", () => {
    const client = createQueryClient();
    holdNote(client, "p1", "unsent");
    expect(client.getQueryCache().find({ queryKey: ["held-note", "p1"] })?.gcTime).toBe(Infinity);
  });

  it("is dropped with the rest of the person's data", () => {
    const client = createQueryClient();
    holdNote(client, "p1", "unsent");
    clearPersonData(client);
    expect(readHeldNote(client, "p1")).toBe("");
  });

  it("is never written to browser storage", () => {
    const client = createQueryClient();
    holdNote(client, "p1", "unsent");
    expect(Object.values(localStorage).join()).not.toContain("unsent");
    expect(Object.values(sessionStorage).join()).not.toContain("unsent");
  });
});
