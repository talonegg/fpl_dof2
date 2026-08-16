/**
 * A categorical chart of forecasts, where **the band is the mark and the mean is an annotation on
 * it** — the one chart in this app that plots a predicted number rather than a counted one.
 *
 * **Why this shape, and why it is the only forecast chart here.** E6-S5 requires that uncertainty be
 * visible on every forecast chart: "a predicted 5.2 points that could plausibly be anything from 0 to
 * 15 must not render as though it were a measurement" (DP-09, Invariant 6). The usual way to break
 * that rule is a bar chart of expected points, because a bar's length *is* its claim and a bar drawn
 * to 5.2 claims 5.2. So this draws the range first, at full weight, and marks the mean inside it as a
 * tick. Read at a glance it shows a width; the point estimate has to be looked for. That is the
 * correct order of emphasis for a number with a standard deviation around half its own mean, and it
 * makes two overlapping forecasts *look* like what they are — indistinguishable.
 *
 * **A missing standard deviation is not a zero-width band.** `uncertaintyBand` returns null and this
 * renders the row as explicitly unquantified rather than as a bare tick, because a bare tick is
 * visually a measurement. Silent degradation is worse than visible degradation (DP-15).
 *
 * Same construction as `LineChart` and `BarChart`: fixed `viewBox` scaled by CSS so nothing ever
 * measures a container (jsdom has no layout engine), colour from `tokens.css` only, `role="img"` with
 * an accessible name, and a written readout beside the picture for anyone the picture does not serve.
 */

import { extentOf, makeScale, padExtent, ticks, uncertaintyBand } from "./geometry";
import "./charts.css";

const BOX = { width: 640, left: 104, right: 16, top: 14, bottom: 26 };
const ROW_HEIGHT = 30;

const PLOT_LEFT = BOX.left;
const PLOT_RIGHT = BOX.width - BOX.right;

export interface IntervalDatum {
  key: string;
  /** Short name for the row's axis label. Long names are given room, not truncated silently. */
  label: string;
  mean: number;
  /** Undefined means the uncertainty was not published — rendered as such, never as certainty. */
  sd?: number;
  /**
   * The row in words: the mean, its band, and anything the reader needs with them. Used as the
   * row's tooltip and as its entry in the readout below the plot, so the chart is fully usable
   * without seeing it.
   */
  statement: string;
}

export interface IntervalChartProps {
  title: string;
  summary: string;
  data: readonly IntervalDatum[];
  /** Half-width of the drawn band, in standard deviations. Defaults to `BAND_SIGMAS`. */
  sigmas?: number;
  /** Lower clamp for the band. Zero by default; `null` for a quantity that can go negative. */
  floor?: number | null;
  valueTickLabel?: (value: number) => string;
  emptyMessage?: string;
  testId?: string;
}

export function IntervalChart({
  title,
  summary,
  data,
  sigmas,
  floor = 0,
  valueTickLabel = (v) => String(Math.round(v * 100) / 100),
  emptyMessage = "No forecast to show.",
  testId,
}: IntervalChartProps) {
  const rows = data.map((datum) => ({
    datum,
    band: uncertaintyBand(datum.mean, datum.sd, { sigmas, floor }),
  }));

  // The domain must cover the bands, not just the means: scaling to the means and letting the bands
  // overflow the plot would clip exactly the part of the picture this chart exists to show.
  const values = rows.flatMap(({ datum, band }) =>
    band === null ? [datum.mean] : [datum.mean, band.low, band.high],
  );
  const extent = extentOf(values);

  if (extent === null || rows.length === 0) {
    return (
      <figure className="chart" data-testid={testId}>
        <figcaption className="chart-title">{title}</figcaption>
        <p className="chart-empty">{emptyMessage}</p>
      </figure>
    );
  }

  const height = BOX.top + rows.length * ROW_HEIGHT + BOX.bottom;
  // Anchored at zero: these are counted-in-points quantities and a floating baseline would make a
  // band from 3.9 to 8.3 look like it excludes low returns when it does not.
  const domain = padExtent(extent, { includeZero: true, minSpan: 1 });
  const sx = makeScale(domain, PLOT_LEFT, PLOT_RIGHT);
  const xTicks = ticks(domain, 4);

  return (
    <figure className="chart" data-testid={testId}>
      <figcaption className="chart-title">{title}</figcaption>
      <svg
        className="chart-svg"
        viewBox={`0 0 ${BOX.width} ${height}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={`${title}. ${summary}`}
      >
        <title>{title}</title>
        <desc>{summary}</desc>

        {xTicks.map((value) => (
          <g key={`x-${value}`}>
            <line
              className="chart-gridline"
              x1={sx(value)}
              x2={sx(value)}
              y1={BOX.top}
              y2={BOX.top + rows.length * ROW_HEIGHT}
            />
            <text
              className="chart-axis-label"
              x={sx(value)}
              y={BOX.top + rows.length * ROW_HEIGHT + 16}
              textAnchor="middle"
            >
              {valueTickLabel(value)}
            </text>
          </g>
        ))}

        {rows.map(({ datum, band }, index) => {
          const centre = BOX.top + index * ROW_HEIGHT + ROW_HEIGHT / 2;
          const meanX = sx(datum.mean);
          return (
            <g key={datum.key} data-interval={datum.key}>
              <title>{datum.statement}</title>
              <text className="chart-axis-label" x={PLOT_LEFT - 8} y={centre + 3} textAnchor="end">
                {datum.label}
              </text>

              {band === null ? (
                // No band to draw, so the row says why in the plot area itself. Drawing the mean
                // alone here would be the precise failure this component exists to avoid.
                <text className="chart-band-missing" x={PLOT_LEFT + 4} y={centre + 3}>
                  uncertainty not published
                </text>
              ) : (
                <>
                  <rect
                    className="chart-band"
                    x={sx(band.low)}
                    y={centre - 8}
                    width={Math.max(1, sx(band.high) - sx(band.low))}
                    height={16}
                  />
                  <line
                    className="chart-band-cap"
                    x1={sx(band.low)}
                    x2={sx(band.low)}
                    y1={centre - 8}
                    y2={centre + 8}
                  />
                  <line
                    className="chart-band-cap"
                    x1={sx(band.high)}
                    x2={sx(band.high)}
                    y1={centre - 8}
                    y2={centre + 8}
                  />
                  <line
                    className="chart-band-mean"
                    x1={meanX}
                    x2={meanX}
                    y1={centre - 9}
                    y2={centre + 9}
                  />
                </>
              )}
            </g>
          );
        })}
      </svg>

      {/* The readout, not a legend: it carries the numbers the plot deliberately de-emphasises, so
          nothing here is available only to a reader who can see the picture (NFR-14, DP-09). */}
      <ul className="chart-readout" data-testid={testId ? `${testId}-readout` : undefined}>
        {data.map((datum) => (
          <li key={datum.key}>{datum.statement}</li>
        ))}
      </ul>
      <p className="chart-summary">{summary}</p>
    </figure>
  );
}
