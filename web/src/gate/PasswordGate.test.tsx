import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LockButton, PasswordGate } from "./PasswordGate";
import { ThemeProvider } from "../theme/ThemeProvider";
import { normaliseHash, sha256Hex, UNLOCK_KEY } from "./hash";

// Any other hash: stands in for "the password was changed".
const HASH = "0".repeat(64);
let correctHash = "";

function App({ hash }: { hash: string }) {
  return (
    <ThemeProvider>
      <PasswordGate expectedHash={hash}>
        <div data-testid="app">secret app</div>
        <LockButton />
      </PasswordGate>
    </ThemeProvider>
  );
}

async function enter(password: string) {
  fireEvent.change(screen.getByTestId("gate-input"), { target: { value: password } });
  await act(async () => {
    fireEvent.submit(screen.getByTestId("gate-input").closest("form")!);
  });
}

beforeEach(async () => {
  window.localStorage.clear();
  correctHash = await sha256Hex("correct horse");
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("sha256Hex", () => {
  it("matches sha256sum of the UTF-8 bytes, as lowercase hex", async () => {
    expect(await sha256Hex("abc")).toBe("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
    expect(normaliseHash("  BA78\n")).toBe("ba78");
  });
});

describe("PasswordGate", () => {
  it("unlocks with the correct password and remembers the hash, never the password", async () => {
    render(<App hash={correctHash.toUpperCase()} />);
    expect(screen.queryByTestId("app")).toBeNull();
    await enter("correct horse");
    await waitFor(() => expect(screen.getByTestId("app")).toBeTruthy());
    expect(window.localStorage.getItem(UNLOCK_KEY)).toBe(correctHash);
    expect(JSON.stringify({ ...window.localStorage })).not.toContain("correct horse");
  });

  it("rejects a wrong password with an announced error and keeps the app unrendered", async () => {
    render(<App hash={correctHash} />);
    await enter("wrong");
    const error = screen.getByTestId("gate-error");
    await waitFor(() => expect(error.textContent).toMatch(/incorrect password/i));
    expect(error.getAttribute("aria-live")).toBe("assertive");
    expect(screen.getByTestId("gate-input").getAttribute("aria-invalid")).toBe("true");
    expect(screen.queryByTestId("app")).toBeNull();
    expect(window.localStorage.getItem(UNLOCK_KEY)).toBeNull();
  });

  it("stays unlocked on a later visit with the same hash", () => {
    window.localStorage.setItem(UNLOCK_KEY, correctHash);
    render(<App hash={correctHash} />);
    expect(screen.getByTestId("app")).toBeTruthy();
  });

  it("re-locks when the configured hash changes", () => {
    window.localStorage.setItem(UNLOCK_KEY, correctHash);
    render(<App hash={HASH} />);
    expect(screen.queryByTestId("app")).toBeNull();
    expect(screen.getByTestId("gate")).toBeTruthy();
  });

  it("locks again from the lock control and forgets the unlock", () => {
    window.localStorage.setItem(UNLOCK_KEY, correctHash);
    render(<App hash={correctHash} />);
    fireEvent.click(screen.getByTestId("lock-button"));
    expect(screen.queryByTestId("app")).toBeNull();
    expect(window.localStorage.getItem(UNLOCK_KEY)).toBeNull();
  });

  it.each(["", "   "])("fails closed when no hash was configured (%j)", async (hash) => {
    window.localStorage.setItem(UNLOCK_KEY, "");
    render(<App hash={hash} />);
    expect(screen.getByTestId("gate-not-configured").textContent).toContain(
      "Site locked: password not configured",
    );
    expect(screen.queryByTestId("gate-input")).toBeNull();
    expect(screen.queryByTestId("app")).toBeNull();
  });

  it("does not fetch anything before unlock", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    render(<App hash={correctHash} />);
    await enter("wrong");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("has a labelled input and a show/hide toggle", () => {
    render(<App hash={correctHash} />);
    const input = screen.getByLabelText("Password") as HTMLInputElement;
    expect(input.type).toBe("password");
    fireEvent.click(screen.getByTestId("gate-toggle"));
    expect(input.type).toBe("text");
    expect(screen.getByTestId("gate-toggle").getAttribute("aria-pressed")).toBe("true");
  });
});

describe("PasswordGate theme", () => {
  it("offers the app's theme toggle on the gate, sharing the app's theme state and storage", async () => {
    window.localStorage.setItem("fpl-dof.theme", "dark");
    render(<App hash={correctHash} />);
    const toggle = screen.getByTestId("theme-toggle");
    expect(toggle.getAttribute("data-preference")).toBe("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    fireEvent.click(toggle); // dark -> system
    expect(window.localStorage.getItem("fpl-dof.theme")).toBe("system");
    expect(document.documentElement.getAttribute("data-theme")).toBeNull();
    fireEvent.click(toggle); // system -> light
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");

    // The choice made on the gate carries into the app after unlock.
    await enter("correct horse");
    await waitFor(() => expect(screen.getByTestId("app")).toBeTruthy());
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(window.localStorage.getItem("fpl-dof.theme")).toBe("light");
  });

  it("shows the theme toggle on the not-configured screen too", async () => {
    render(<App hash="" />);
    expect(screen.getByTestId("gate-not-configured").querySelector('[data-testid="theme-toggle"]')).toBeTruthy();
  });
});
