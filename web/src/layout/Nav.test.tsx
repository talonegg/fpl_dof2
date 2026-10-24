import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, screen, within } from "@testing-library/react";
import { installFetchStub, renderApp, resetAppState } from "../test/render";

describe("the More menu closes when the reader leaves it", () => {
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

    fireEvent.pointerDown(screen.getByTestId("bottom-more-menu"));
    expect(more.getAttribute("aria-expanded")).toBe("true");

    fireEvent.pointerDown(document.body);
    expect(more.getAttribute("aria-expanded")).toBe("false");
  });

  it("closes when focus tabs out of the menu, stays open while it moves between entries", async () => {
    renderApp("/");
    await screen.findByTestId("bottom-bar");
    const more = screen.getByTestId("bottom-more");
    fireEvent.click(more);
    const [first, second] = within(screen.getByTestId("bottom-more-menu")).getAllByRole("link");
    expect(document.activeElement).toBe(first);

    act(() => second.focus());
    expect(more.getAttribute("aria-expanded")).toBe("true");

    act(() => screen.getByTestId("bottom-home").focus());
    expect(more.getAttribute("aria-expanded")).toBe("false");
  });
});
