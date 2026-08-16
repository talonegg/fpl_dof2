import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { ThemeProvider, useTheme } from "./ThemeProvider";
import { ThemeToggle } from "../layout/ThemeToggle";

function Probe() {
  const { preference, resolved } = useTheme();
  return (
    <span data-testid="probe" data-preference={preference} data-resolved={resolved}>
      {preference}/{resolved}
    </span>
  );
}

function renderTheme() {
  return render(
    <ThemeProvider>
      <ThemeToggle />
      <Probe />
    </ThemeProvider>,
  );
}

describe("ThemeProvider", () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("defaults to following the system and stamps no attribute", () => {
    renderTheme();
    expect(screen.getByTestId("probe").getAttribute("data-preference")).toBe("system");
    // No attribute means the `prefers-color-scheme` block in tokens.css decides.
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
  });

  it("cycles light, dark, then back to system, stamping the root each time", () => {
    renderTheme();
    const toggle = screen.getByTestId("theme-toggle");

    fireEvent.click(toggle);
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");

    fireEvent.click(toggle);
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");

    fireEvent.click(toggle);
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
    expect(screen.getByTestId("probe").getAttribute("data-preference")).toBe("system");
  });

  it("persists the choice and restores it on the next visit", () => {
    const first = renderTheme();
    fireEvent.click(screen.getByTestId("theme-toggle"));
    fireEvent.click(screen.getByTestId("theme-toggle"));
    expect(window.localStorage.getItem("fpl-dof.theme")).toBe("dark");
    first.unmount();

    renderTheme();
    expect(screen.getByTestId("probe").getAttribute("data-preference")).toBe("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  it("ignores a corrupt stored value rather than throwing", () => {
    window.localStorage.setItem("fpl-dof.theme", "chartreuse");
    renderTheme();
    expect(screen.getByTestId("probe").getAttribute("data-preference")).toBe("system");
  });
});
