import { useEffect, useState } from "react";
import { fetchHealth, healthLabel, type HealthView } from "./health";

export function HealthStatus() {
  const [view, setView] = useState<HealthView>({ kind: "checking" });

  useEffect(() => {
    let cancelled = false;
    void fetchHealth().then((next) => {
      if (!cancelled) setView(next);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return <p role="status">{healthLabel(view)}</p>;
}
