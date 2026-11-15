export type Theme = "day" | "night";

const KEY = "theme";

/** The remembered theme. Storage can be blocked (private windows, site data off): then day. */
export function readTheme(): Theme {
  try {
    return localStorage.getItem(KEY) === "night" ? "night" : "day";
  } catch {
    return "day";
  }
}

export function saveTheme(theme: Theme): void {
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    // Not remembered, still applied for this visit.
  }
}

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset["theme"] = theme;
}
