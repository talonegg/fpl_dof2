import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { Header, describeTrigger } from "./Header";
import { meta } from "../test/fixtures";
import { formatLocalDateTime } from "../format";

describe("Header 'As at' line (ORC-03)", () => {
  it("shows the snapshot's as_of and what started the run", () => {
    const stamped = { ...meta, as_of: "2026-08-10T09:00:00Z", trigger: "change:price,status" };
    render(<Header meta={stamped} />);
    expect(screen.getByTestId("header-as-at").textContent).toBe(
      `As at ${formatLocalDateTime("2026-08-10T09:00:00Z")} · after a price, status change`,
    );
  });

  it("names a run a results change started a results refresh (LIVE-02)", () => {
    const stamped = { ...meta, as_of: "2026-10-31T21:07:00Z", trigger: "change:results" };
    render(<Header meta={stamped} />);
    expect(screen.getByTestId("header-as-at").textContent).toBe(
      `As at ${formatLocalDateTime("2026-10-31T21:07:00Z")} · results refresh`,
    );
    expect(describeTrigger("change:prices,results")).toBe("results refresh, with a prices change");
  });

  it("falls back to generated_at with no trigger on an older contract", () => {
    render(<Header meta={meta} />);
    expect(screen.getByTestId("header-as-at").textContent).toBe(
      `As at ${formatLocalDateTime(meta.generated_at)}`,
    );
  });
});
