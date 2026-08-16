import type { ReactNode } from "react";

interface PlaceholderProps {
  /** Story that will build this view out, e.g. "E6-S4". */
  story: string;
  title: string;
  /** What the finished view will do, in one sentence, taken from the epic. */
  summary: string;
  /** Anything already usable here — kept honest, so a placeholder never pretends to be a feature. */
  children?: ReactNode;
}

/**
 * A route that exists but is not built yet.
 *
 * Deliberately says which story fills it in: the shell ships before the views (E6-S1), and an
 * unlabelled empty page is indistinguishable from a broken one.
 */
export function Placeholder({ story, title, summary, children }: PlaceholderProps) {
  return (
    <section className="placeholder" data-testid={`placeholder-${story}`}>
      <h2>{title}</h2>
      <p className="placeholder-story">Coming in {story}</p>
      <p className="placeholder-summary">{summary}</p>
      {children}
    </section>
  );
}
