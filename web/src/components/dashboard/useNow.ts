import { useEffect, useState } from "react";

/**
 * A clock that re-renders the countdown, cheaply.
 *
 * Once a minute, plus whenever the tab is looked at again. A per-second tick would be a re-render
 * every second for a figure that is quoted in hours, and the realistic failure mode is not a stale
 * minute — it is a phone that has had this page open in a background tab since Tuesday and shows
 * Tuesday's countdown when it is picked up on Friday. The focus and visibility listeners are the
 * part that actually matters; the interval is the cheap belt to their braces.
 *
 * The clock is read here, at the edge, and passed into the pure formatting functions as an
 * argument (DP-03).
 */
export function useNow(intervalMs = 60_000): Date {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const tick = () => setNow(new Date());
    const timer = window.setInterval(tick, intervalMs);
    const onVisible = () => {
      if (document.visibilityState === "visible") tick();
    };

    window.addEventListener("focus", tick);
    document.addEventListener("visibilitychange", onVisible);

    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", tick);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [intervalMs]);

  return now;
}
