import { api } from "../api/client";

export type HealthView =
  { kind: "checking" } | { kind: "healthy" } | { kind: "unhealthy" } | { kind: "unreachable" };

export function healthLabel(view: HealthView): string {
  switch (view.kind) {
    case "checking":
      return "Checking API…";
    case "healthy":
      return "API: healthy";
    case "unhealthy":
      return "API: unhealthy — database unreachable";
    case "unreachable":
      return "API: unreachable";
  }
}

export async function fetchHealth(): Promise<HealthView> {
  try {
    const { data, response } = await api.GET("/api/v1/health");
    if (data?.status === "healthy") return { kind: "healthy" };
    if (response.status === 503) return { kind: "unhealthy" };
    return { kind: "unreachable" };
  } catch {
    return { kind: "unreachable" };
  }
}
