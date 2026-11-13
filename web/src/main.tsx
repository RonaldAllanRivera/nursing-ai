import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./styles/app.css";

const root = document.getElementById("root");
if (!root) throw new Error("Missing #root element");

// `pnpm dev:mock` answers the API from the demo cases. The import sits behind a build-time
// constant, so other modes (and the production bundle) never contain the mock code.
if (import.meta.env.MODE === "mock") {
  const { worker } = await import("./mocks/browser");
  await worker.start({ onUnhandledFrame: "bypass" });
}

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
