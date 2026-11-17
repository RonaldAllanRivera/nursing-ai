import { useQuery } from "@tanstack/react-query";
import { Icon } from "../components/Icon";
import { DEMO_BANNER, offeredFrom } from "../session/signInOptions";
import { signInOptionsQuery } from "../session/session";

/**
 * On every screen while the demo is on. A standing caution, not an alarm: amber (check this) with a
 * flag and words, never red. Without the options (still loading, or they failed) there is no banner.
 */
export function DemoBanner() {
  const options = useQuery(signInOptionsQuery);
  if (!offeredFrom(options.data).banner) return null;
  return (
    <p className="flex items-start justify-start gap-2 border-b border-rule bg-review-tint px-4 py-2 text-left text-14 font-semibold text-review sm:items-center sm:justify-center sm:text-center">
      <Icon name="flag" className="mt-0.5 sm:mt-0" />
      <span>{DEMO_BANNER}</span>
    </p>
  );
}
