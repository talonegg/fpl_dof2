import { useEffect, useState } from "react";

/**
 * Track a media query from JavaScript.
 *
 * Layout is CSS's job wherever it can be, and nearly all of the scout view's responsiveness is. The
 * exception is the virtualiser: it needs a row height in pixels before anything renders, and the
 * phone layout's row is a card rather than a table row. That number cannot come from a stylesheet,
 * so this one breakpoint is mirrored here — and only this one.
 *
 * Guarded the same way `ThemeProvider` guards `prefers-color-scheme`: an environment without
 * `matchMedia` (jsdom, chiefly) reports false and gets the wide layout, rather than throwing.
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() =>
    typeof window.matchMedia === "function" ? window.matchMedia(query).matches : false,
  );

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const list = window.matchMedia(query);
    setMatches(list.matches);
    const onChange = (event: MediaQueryListEvent) => setMatches(event.matches);
    list.addEventListener("change", onChange);
    return () => list.removeEventListener("change", onChange);
  }, [query]);

  return matches;
}

/**
 * The one breakpoint the scout view expresses twice.
 *
 * Below this width a dense grid stops being a table and starts being a horizontal scroll with a
 * name column bolted to it, so the rows become cards instead. Kept beside the stylesheet rule it
 * mirrors, in `scout.css`, so the pair are changed together.
 */
export const PHONE_QUERY = "(max-width: 640px)";
