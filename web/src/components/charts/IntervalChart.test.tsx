import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { IntervalChart } from "./IntervalChart";

function renderChart(data: Parameters<typeof IntervalChart>[0]["data"]) {
  return render(
    <IntervalChart
      testId="interval"
      title="Expected points"
      summary="A summary of the forecast."
      data={data}
    />,
  );
}

const RAYA = { key: "1", label: "Raya", mean: 4.2, sd: 1.89, statement: "Raya: 4.20 expected" };

describe("IntervalChart", () => {
  it("draws a band for every forecast that publishes its uncertainty", () => {
    renderChart([RAYA, { key: "2", label: "Watkins", mean: 4.52, sd: 2.03, statement: "Watkins" }]);
    expect(screen.getByTestId("interval").querySelectorAll(".chart-band")).toHaveLength(2);
  });

  it("draws the mean as a tick on the band, never as the band itself", () => {
    // The band is the mark; the mean is an annotation on it. A chart where the mean is the only
    // thing drawn is a chart that reads as a measurement (Invariant 6, DP-09).
    const chart = renderChart([RAYA]).container;
    expect(chart.querySelectorAll(".chart-band-mean")).toHaveLength(1);
    expect(chart.querySelectorAll(".chart-band")).toHaveLength(1);
  });

  it("says so when a forecast publishes no uncertainty, instead of drawing a bare point", () => {
    const chart = renderChart([
      { key: "3", label: "Mbeumo", mean: 3.2, statement: "Mbeumo: 3.20, uncertainty unpublished" },
    ]).container;
    expect(chart.querySelectorAll(".chart-band")).toHaveLength(0);
    expect(chart.querySelectorAll(".chart-band-mean")).toHaveLength(0);
    expect(chart.textContent).toContain("uncertainty not published");
  });

  it("scales to the widest band, so no band is clipped by the plot edge", () => {
    // A domain taken from the means alone would cut off exactly what the chart exists to show.
    const chart = renderChart([{ ...RAYA, mean: 4.2, sd: 6 }]).container;
    const band = chart.querySelector(".chart-band") as SVGRectElement;
    const svg = chart.querySelector("svg") as SVGSVGElement;
    const [, , boxWidth] = (svg.getAttribute("viewBox") ?? "").split(" ").map(Number);

    const x = Number(band.getAttribute("x"));
    const width = Number(band.getAttribute("width"));
    expect(x).toBeGreaterThanOrEqual(0);
    expect(x + width).toBeLessThanOrEqual(boxWidth);
  });

  it("carries every number in a readout, so the picture is not the only route to it", () => {
    renderChart([RAYA]);
    expect(screen.getByTestId("interval-readout").textContent).toContain("Raya: 4.20 expected");
  });

  it("is an accessible image with a written description", () => {
    renderChart([RAYA]);
    const svg = screen.getByTestId("interval").querySelector("svg");
    expect(svg?.getAttribute("role")).toBe("img");
    expect(svg?.getAttribute("aria-label")).toContain("A summary of the forecast.");
  });

  it("says there is nothing to show rather than rendering an empty axis", () => {
    renderChart([]);
    expect(screen.getByTestId("interval").textContent).toContain("No forecast to show.");
  });

  it("grows its viewBox with the number of rows, so rows never overlap", () => {
    const one = renderChart([RAYA]).container.querySelector("svg")?.getAttribute("viewBox");
    const four = render(
      <IntervalChart
        title="t"
        summary="s"
        data={[1, 2, 3, 4].map((n) => ({ ...RAYA, key: String(n) }))}
      />,
    ).container
      .querySelector("svg")
      ?.getAttribute("viewBox");

    const height = (box: string | null | undefined) => Number((box ?? "").split(" ")[3]);
    expect(height(four)).toBeGreaterThan(height(one));
  });
});
