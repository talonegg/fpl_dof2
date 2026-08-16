/**
 * A single-series bar chart over a discrete x-axis.
 *
 * A separate component from `LineChart` because a per-gameweek return genuinely is a bar: points in
 * GW7 are not a continuation of points in GW6, and a line between them draws an interpolation that
 * does not exist. Blanks and doubles make that worse — a line would slope through a gameweek the
 * player did not play.
 *
 * Same construction as `LineChart`: fixed `viewBox`, colour from tokens only, an accessible name and
 * a written summary beside the picture.
 */

import { extentOf, makeScale, padExtent, ticks } from "./geometry";
import "./charts.css";

const BOX = { width: 640, height: 180, left: 46, right: 12, top: 12, bottom: 28 };

const PLOT_LEFT = BOX.left;
const PLOT_RIGHT = BOX.width - BOX.right;
const PLOT_TOP = BOX.top;
const PLOT_BOTTOM = BOX.height - BOX.bottom;

export interface BarDatum {
  /** Position on the axis. Bars are laid out in the order given, not by this value. */
  x: number;
  y: number;
  /** Axis label for this bar. */
  label: string;
  /** Tooltip, where the bar's height abbreviates something longer. */
  title?: string;
}

export interface BarChartProps {
  title: string;
  summary: string;
  data: readonly BarDatum[];
  yTickLabel?: (y: number) => string;
  emptyMessage?: string;
  testId?: string;
}

export function BarChart({
  title,
  summary,
  data,
  yTickLabel = (y) => String(Math.round(y * 100) / 100),
  emptyMessage = "No data yet.",
  testId,
}: BarChartProps) {
  const yExtent = extentOf(data.map((d) => d.y));

  if (yExtent === null) {
    return (
      <figure className="chart" data-testid={testId}>
        <figcaption className="chart-title">{title}</figcaption>
        <p className="chart-empty">{emptyMessage}</p>
      </figure>
    );
  }

  // A bar chart is always read against zero — the length of the bar is the claim it makes.
  const yDomain = padExtent(yExtent, { includeZero: true, minSpan: 1 });
  const sy = makeScale(yDomain, PLOT_BOTTOM, PLOT_TOP);
  const baseline = sy(Math.max(yDomain.min, Math.min(0, yDomain.max)));

  const slot = (PLOT_RIGHT - PLOT_LEFT) / Math.max(1, data.length);
  const barWidth = Math.max(2, Math.min(24, slot * 0.68));

  const yTicks = ticks(yDomain, 4);
  const labelStride = Math.max(1, Math.ceil(data.length / 12));

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

        {data.map((datum, index) => {
          const centre = PLOT_LEFT + slot * (index + 0.5);
          const y = sy(datum.y);
          const top = Math.min(y, baseline);
          const height = Math.max(1, Math.abs(baseline - y));
          return (
            <g key={`${datum.label}-${index}`}>
              <rect
                className={datum.y < 0 ? "chart-bar chart-bar-negative" : "chart-bar"}
                x={centre - barWidth / 2}
                y={top}
                width={barWidth}
                height={height}
              >
                <title>{datum.title ?? `${datum.label}: ${datum.y}`}</title>
              </rect>
              {index % labelStride === 0 && (
                <text
                  className="chart-axis-label"
                  x={centre}
                  y={PLOT_BOTTOM + 16}
                  textAnchor="middle"
                >
                  {datum.label}
                </text>
              )}
            </g>
          );
        })}

        <line
          className="chart-axis"
          x1={PLOT_LEFT}
          x2={PLOT_RIGHT}
          y1={baseline}
          y2={baseline}
        />
      </svg>
      <p className="chart-summary">{summary}</p>
    </figure>
  );
}
