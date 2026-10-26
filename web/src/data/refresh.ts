import { useEffect } from "react";
import { refreshPublishedData } from "./store";

/**
 * Re-read the published files when an open app becomes visible again (LIVE-06, R1.4.3 §5 Q5).
 *
 * A matchday refresh lands while the app sits in a background tab or a phone's pocket; this is how
 * the owner sees it without a reload. The only trigger is the document turning visible, so nothing
 * is fetched while it is hidden and there is **no timer**: an app nobody is looking at costs the
 * publisher nothing. The service worker keeps its `NetworkFirst` strategy for these requests, so
 * an offline reader still gets the last cache.
 *
 * Mounted once, by `DataProvider`; the store tells every view that reads it to read again.
 */
export function useRefreshWhenVisible(): void {
  useEffect(() => {
    const onChange = () => {
      if (document.visibilityState === "visible") refreshPublishedData();
    };
    document.addEventListener("visibilitychange", onChange);
    return () => document.removeEventListener("visibilitychange", onChange);
  }, []);
}
