import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { useState } from "react";
import { createAppRouter } from "./app/router";

/** The client is made once by the caller, outside render: StrictMode runs a state initializer twice in development. */
export function App({ queryClient }: { queryClient: QueryClient }) {
  const [router] = useState(() => createAppRouter({ queryClient }));
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}
