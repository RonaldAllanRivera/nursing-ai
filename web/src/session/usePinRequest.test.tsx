import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import { usePinRequest } from "./usePinRequest";

function wrapper() {
  const queryClient = new QueryClient();
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

describe("usePinRequest options", () => {
  it("runs two requests that share a scope one after the other", async () => {
    const order: string[] = [];
    let release: () => void = () => undefined;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    const Wrapper = wrapper();
    const logged = (label: string, gate?: Promise<void>) => async () => {
      order.push(`${label}:start`);
      if (gate) await gate;
      order.push(`${label}:end`);
      return label;
    };
    const first = renderHook(
      () => usePinRequest(logged("first", held), { onSuccess: () => undefined }, { scope: "same" }),
      { wrapper: Wrapper },
    );
    const second = renderHook(
      () => usePinRequest(logged("second"), { onSuccess: () => undefined }, { scope: "same" }),
      { wrapper: Wrapper },
    );
    let done: Promise<boolean>[] = [];
    act(() => {
      done = [first.result.current.run("135790"), second.result.current.run("135790")];
    });
    await waitFor(() => {
      expect(order).toEqual(["first:start"]);
    });
    // The second waits for the first to finish.
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(order).toEqual(["first:start"]);
    release();
    await act(() => Promise.all(done));
    expect(order).toEqual(["first:start", "first:end", "second:start", "second:end"]);
  });

  it("runs onMutate before the request, and clear() forgets the last failure", async () => {
    const calls: string[] = [];
    const { result } = renderHook(
      () =>
        usePinRequest(
          () => {
            calls.push("send");
            return Promise.reject(new Error("no"));
          },
          { onSuccess: () => undefined },
          {
            onMutate: () => {
              calls.push("mutate");
            },
          },
        ),
      { wrapper: wrapper() },
    );
    await act(async () => {
      expect(await result.current.run("135790")).toBe(false);
    });
    expect(calls).toEqual(["mutate", "send"]);
    expect(result.current.error).toBeInstanceOf(Error);
    act(() => {
      result.current.clear();
    });
    expect(result.current.error).toBeNull();
  });
});
