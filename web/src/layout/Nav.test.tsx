import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen } from "@testing-library/react";
import { installFetchStub, renderApp, resetAppState } from "../test/render";

describe("the More menu closes on an outside tap", () => {
  beforeEach(() => {
    resetAppState();
    installFetchStub();
  });
  afterEach(() => vi.unstubAllGlobals());

  it("closes when the page is tapped, stays open for a tap inside the menu", async () => {
    renderApp("/");
    await screen.findByTestId("bottom-bar");
    const more = screen.getByTestId("bottom-more");
    fireEvent.click(more);
    expect(more.getAttribute("aria-expanded")).toBe("true");

    fireEvent.mouseDown(screen.getByTestId("bottom-more-menu"));
    expect(more.getAttribute("aria-expanded")).toBe("true");

    fireEvent.mouseDown(document.body);
    expect(more.getAttribute("aria-expanded")).toBe("false");
  });
});
