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
    const { data, error } = await api.GET("/api/v1/health");
    if (data?.status === "healthy") return { kind: "healthy" };
    // Only the API's own answer counts as "unhealthy". A 502 or 503 from a proxy has no such
    // body (openapi-fetch puts a non-2xx body in `error`: empty or text when it is not JSON).
    const body: unknown = error;
    if (typeof body === "object" && body !== null && "database" in body) {
      if (body.database === "unreachable") return { kind: "unhealthy" };
    }
    return { kind: "unreachable" };
  } catch {
    return { kind: "unreachable" };
  }
}
