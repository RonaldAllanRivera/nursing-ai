import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { createQueryClient } from "./app/queryClient";
import "./styles/app.css";
import { applyTheme, readTheme } from "./theme/theme";

applyTheme(readTheme());

// Made once, here, outside render: the API client reads the CSRF token from this client's cache.
const queryClient = createQueryClient();

const root = document.getElementById("root");
if (!root) throw new Error("Missing #root element");

// `pnpm dev:mock` answers the API from the demo cases. The import sits behind a build-time
// constant, so other modes (and the production bundle) never contain the mock code.
let mockFailed = false;
if (import.meta.env.MODE === "mock") {
  try {
    const { worker } = await import("./mocks/browser");
    await worker.start({ onUnhandledFrame: "bypass" });
  } catch (error) {
    // Says why (a bad mock option, say) to whoever opens the console; it never holds a PIN or token.
    console.error("Mock mode could not start.", error);
    mockFailed = true;
  }
}

createRoot(root).render(
  <StrictMode>
    {mockFailed ? (
      <p role="alert" style={{ padding: "1rem" }}>
        Mock mode could not start. It needs the page opened at localhost or over https, not at a
        plain http network address.
      </p>
    ) : (
      <App queryClient={queryClient} />
    )}
  </StrictMode>,
);
