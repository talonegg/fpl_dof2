/**
 * A small multi-series line chart, drawn as inline SVG.
 *
 * **Why not a charting library.** Three reasons, in order of weight:
 *
 * 1. The charts this app needs are a line and a bar over at most a few dozen points. A library's
 *    value is in the cases beyond that, and its cost lands on the NFR-04 initial-payload budget.
 * 2. Colour would leave `tokens.css`. Chart libraries take colours as props, and the moment a series
 *    colour is a prop it is a literal in a component — right in one theme, wrong in the other.
 * 3. jsdom has no layout engine (see `src/test/setup.ts`), so the usual responsive container measures
 *    zero and renders nothing under test. A fixed `viewBox` scaled by CSS is responsive without ever
 *    measuring, which means the chart under test is the chart in the browser.
 *
 * **Legible without colour** (NFR-14, E6-S9). Series are distinguished three ways at once — stroke
 * colour, dash pattern and marker shape — so the chart survives being printed, being read by someone
 * colour-blind, and being rendered in either theme.
 *
 * **Accessible.** The SVG carries `role="img"` and an accessible name, and every chart takes a
 * `summary` that states in words what the picture shows. A chart that only exists as a picture is a
 * chart half the readers do not get.
 */

import type { Point } from "./geometry";
import { extentOf, linePath, makeScale, padExtent, ticks } from "./geometry";
import "./charts.css";

/** The plot box, in viewBox units. Fixed, then scaled to the container by CSS. */
const BOX = { width: 640, height: 200, left: 46, right: 12, top: 12, bottom: 28 };

const PLOT_LEFT = BOX.left;
const PLOT_RIGHT = BOX.width - BOX.right;
const PLOT_TOP = BOX.top;
const PLOT_BOTTOM = BOX.height - BOX.bottom;

/**
 * Series variants: colour, dash and marker together.
 *
 * The colours are existing semantic tokens rather than new ones. `--accent` is the app's primary
 * emphasis and `--focus-ring` its secondary; `--text-muted` is deliberately recessive, which is what
 * a context series should be. No new token, and no literal.
 *
 * **Four, because `/compare` allows four players** (`COMPARE_MAX`), and one overlaid line each is the
 * whole point of that view. The fourth borrows `--warn-border`, which is the only remaining token
 * with a distinct hue and a defined value in both themes. The role mismatch is real and is the same
 * trade the first three already make — a series is not "accent-coloured" in any semantic sense
 * either. The alternative is a new colour token that exists only to be a fourth line, and a palette
 * that grows one entry per chart is how a hex code eventually lands in a component.
 */
export const SERIES_VARIANTS = [
  { stroke: "var(--accent)", dash: undefined, marker: "circle" },
  { stroke: "var(--focus-ring)", dash: "6 3", marker: "square" },
  { stroke: "var(--text-muted)", dash: "2 3", marker: "diamond" },
  { stroke: "var(--warn-border)", dash: "5 2 1 2", marker: "triangle" },
] as const;

export type SeriesVariant = 0 | 1 | 2 | 3;

export interface ChartSeries {
  key: string;
  label: string;
  /** Ascending in x. Gaps are allowed and are drawn as gaps — an absent value is not a zero. */
  points: readonly Point[];
  variant: SeriesVariant;
}

export interface LineChartProps {
  title: string;
  /** What the picture shows, in words. Becomes the chart's accessible description. */
  summary: string;
  series: readonly ChartSeries[];
  xTickLabel: (x: number) => string;
  yTickLabel?: (y: number) => string;
  /** Anchor the y-axis at zero. On for counted quantities, off for price and ownership. */
  includeZero?: boolean;
  /** Smallest y span, so a flat series does not become a scaleless line. */
  minSpan?: number;
  /** Shown in place of the plot when there is nothing to draw (DP-15). */
  emptyMessage?: string;
  testId?: string;
}

function Marker({ shape, x, y, stroke }: { shape: string; x: number; y: number; stroke: string }) {
  if (shape === "square") {
    return <rect x={x - 2.6} y={y - 2.6} width={5.2} height={5.2} fill={stroke} />;
  }
  if (shape === "diamond") {
    return <path d={`M${x} ${y - 3.4}L${x + 3.4} ${y}L${x} ${y + 3.4}L${x - 3.4} ${y}Z`} fill={stroke} />;
  }
  if (shape === "triangle") {
    return <path d={`M${x} ${y - 3.4}L${x + 3.2} ${y + 2.6}L${x - 3.2} ${y + 2.6}Z`} fill={stroke} />;
  }
  return <circle cx={x} cy={y} r={2.6} fill={stroke} />;
}

export function LineChart({
  title,
  summary,
  series,
  xTickLabel,
  yTickLabel = (y) => String(Math.round(y * 100) / 100),
  includeZero = true,
  minSpan = 1,
  emptyMessage = "No data yet.",
  testId,
}: LineChartProps) {
  const allPoints = series.flatMap((s) => s.points);
  const xExtent = extentOf(allPoints.map((p) => p.x));
  const yExtent = extentOf(allPoints.map((p) => p.y));

  if (xExtent === null || yExtent === null) {
    return (
      <figure className="chart" data-testid={testId}>
        <figcaption className="chart-title">{title}</figcaption>
        <p className="chart-empty">{emptyMessage}</p>
      </figure>
    );
  }

  const xDomain = padExtent(xExtent, { includeZero: false, minSpan: 1, padFraction: 0 });
  const yDomain = padExtent(yExtent, { includeZero, minSpan });

  const sx = makeScale(xDomain, PLOT_LEFT, PLOT_RIGHT);
  const sy = makeScale(yDomain, PLOT_BOTTOM, PLOT_TOP);

  const yTicks = ticks(yDomain, 4);
  // At most eight x labels, whatever the series length: the axis is 640 units wide and 38 gameweek
  // labels on it is a grey smear, not an axis.
  const xValues = Array.from(new Set(allPoints.map((p) => p.x))).sort((a, b) => a - b);
  const xStride = Math.max(1, Math.ceil(xValues.length / 8));
  const xTicks = xValues.filter((_, i) => i % xStride === 0);

  return (
    <figure className="chart" data-testid={testId}>
      <figcaption className="chart-title">{title}</figcaption>
      <svg
        className="chart-svg"
        viewBox={`0 0 ${BOX.width} ${BOX.height}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={`${title}. ${summary}`}
      >
        <title>{title}</title>
        <desc>{summary}</desc>

        {yTicks.map((value) => (
          <g key={`y-${value}`}>
            <line
              className="chart-gridline"
              x1={PLOT_LEFT}
              x2={PLOT_RIGHT}
              y1={sy(value)}
              y2={sy(value)}
            />
            <text className="chart-axis-label" x={PLOT_LEFT - 6} y={sy(value) + 3} textAnchor="end">
              {yTickLabel(value)}
            </text>
          </g>
        ))}

        {xTicks.map((value) => (
          <text
            key={`x-${value}`}
            className="chart-axis-label"
            x={sx(value)}
            y={PLOT_BOTTOM + 16}
            textAnchor="middle"
          >
            {xTickLabel(value)}
          </text>
        ))}

        <line
          className="chart-axis"
          x1={PLOT_LEFT}
          x2={PLOT_RIGHT}
          y1={PLOT_BOTTOM}
          y2={PLOT_BOTTOM}
        />

        {series.map((s) => {
          const variant = SERIES_VARIANTS[s.variant];
          const scaled = s.points.map((p) => ({ x: sx(p.x), y: sy(p.y) }));
          return (
            <g key={s.key} data-series={s.key}>
              <path
                className="chart-line"
                d={linePath(scaled)}
                stroke={variant.stroke}
                strokeDasharray={variant.dash}
                fill="none"
              />
              {/* Markers only when the series is sparse enough for them to read as marks rather
                  than as a thickened line. */}
              {scaled.length <= 24 &&
                scaled.map((p, i) => (
                  <Marker
                    key={`${s.key}-${i}`}
                    shape={variant.marker}
                    x={p.x}
                    y={p.y}
                    stroke={variant.stroke}
                  />
                ))}
            </g>
          );
        })}
      </svg>

      {series.length > 1 && (
        <ul className="chart-legend">
          {series.map((s) => (
            <li key={s.key} className={`chart-legend-item chart-variant-${s.variant}`}>
              <span aria-hidden="true" className="chart-legend-swatch" />
              {s.label}
            </li>
          ))}
        </ul>
      )}
      <p className="chart-summary">{summary}</p>
    </figure>
  );
}
