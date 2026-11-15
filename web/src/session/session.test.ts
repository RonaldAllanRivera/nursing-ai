import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import { clearPersonData, sessionKey, personasQuery } from "./session";

describe("clearPersonData", () => {
  it("drops the last person's queries and mutations, and keeps who is signed in and the sign-in list", async () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(sessionKey, { id: "s" });
    queryClient.setQueryData(personasQuery.queryKey, []);
    queryClient.setQueryData(["patients"], ["a patient"]);

    const done = queryClient.getMutationCache().build(queryClient, {
      mutationFn: (text: string) => Promise.resolve(text),
    });
    await done.execute("a rough note");
    const failed = queryClient.getMutationCache().build(queryClient, {
      mutationFn: (text: string) => Promise.reject(new Error(text)),
    });
    await failed.execute("another rough note").catch(() => undefined);
    expect(queryClient.getMutationCache().getAll()).toHaveLength(2);

    clearPersonData(queryClient);

    expect(queryClient.getMutationCache().getAll()).toHaveLength(0);
    expect(queryClient.getQueryData(["patients"])).toBeUndefined();
    expect(queryClient.getQueryData(sessionKey)).toEqual({ id: "s" });
    expect(queryClient.getQueryData(personasQuery.queryKey)).toEqual([]);
  });
});
