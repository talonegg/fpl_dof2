import {
  createContext,
  useCallback,
  useContext,
  useId,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import { normaliseHash, sha256Hex, UNLOCK_KEY } from "./hash";
import { ThemeToggle } from "../layout/ThemeToggle";
import "./PasswordGate.css";

/**
 * A client-side password gate: **deterrence only.** The published `data/v1/*.json` and the JS bundle
 * stay publicly fetchable; the gate only stops the app from rendering (and so from fetching data)
 * until the reader enters the password.
 *
 * Fails closed: with no hash configured at build time the app is never rendered.
 * The unlock is remembered as the *hash* that was unlocked, so changing the password re-locks.
 */

const LockContext = createContext<(() => void) | null>(null);

/** `lock()` from the surrounding gate, or null when there is no gate (e.g. in component tests). */
export function useLock(): (() => void) | null {
  return useContext(LockContext);
}

function readUnlocked(expected: string): boolean {
  try {
    return (
      expected !== "" &&
      normaliseHash(window.localStorage.getItem(UNLOCK_KEY)) === expected
    );
  } catch {
    return false;
  }
}

export function PasswordGate({
  expectedHash,
  children,
}: {
  expectedHash: string;
  children: ReactNode;
}) {
  const expected = normaliseHash(expectedHash);
  const [unlocked, setUnlocked] = useState(() => readUnlocked(expected));

  const lock = useCallback(() => {
    try {
      window.localStorage.removeItem(UNLOCK_KEY);
    } catch {
      /* storage unavailable: still lock this session */
    }
    setUnlocked(false);
  }, []);

  if (expected === "") {
    return (
      <main className="gate" data-testid="gate-not-configured">
        <div className="gate-theme">
          <ThemeToggle />
        </div>
        <div className="gate-card">
          <h1 className="gate-title">Site locked: password not configured</h1>
          <p className="gate-text">
            This build has no password hash, so the app stays locked. Set the
            FPL_PASSWORD_HASH secret and redeploy.
          </p>
        </div>
      </main>
    );
  }

  if (!unlocked) {
    return (
      <PasswordForm
        expected={expected}
        onUnlock={() => {
          try {
            window.localStorage.setItem(UNLOCK_KEY, expected);
          } catch {
            /* storage unavailable: unlock for this session only */
          }
          setUnlocked(true);
        }}
      />
    );
  }

  return <LockContext.Provider value={lock}>{children}</LockContext.Provider>;
}

function PasswordForm({
  expected,
  onUnlock,
}: {
  expected: string;
  onUnlock: () => void;
}) {
  const inputId = useId();
  const errorId = useId();
  const [value, setValue] = useState("");
  const [show, setShow] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(""); // cleared first so a repeated wrong attempt is announced again
    const hash = await sha256Hex(value);
    setBusy(false);
    if (hash === expected) {
      onUnlock();
    } else {
      setError("Incorrect password. Try again.");
      setValue("");
    }
  }

  return (
    <main className="gate" data-testid="gate">
        <div className="gate-theme">
          <ThemeToggle />
        </div>
      <form className="gate-card" onSubmit={(e) => void submit(e)} noValidate>
        <h1 className="gate-title">FPL DOF</h1>
        <p className="gate-text">Enter the password to continue.</p>
        <label className="gate-label" htmlFor={inputId}>
          Password
        </label>
        <div className="gate-row">
          <input
            id={inputId}
            className="gate-input"
            type={show ? "text" : "password"}
            autoComplete="current-password"
            autoFocus
            value={value}
            onChange={(e) => setValue(e.target.value)}
            aria-invalid={error !== ""}
            aria-describedby={errorId}
            data-testid="gate-input"
          />
          <button
            type="button"
            className="gate-toggle"
            onClick={() => setShow((s) => !s)}
            aria-pressed={show}
            aria-controls={inputId}
            data-testid="gate-toggle"
          >
            {show ? "Hide" : "Show"}
            <span className="visually-hidden"> password</span>
          </button>
        </div>
        <p
          id={errorId}
          className="gate-error"
          role="alert"
          aria-live="assertive"
          data-testid="gate-error"
        >
          {error}
        </p>
        <button
          type="submit"
          className="gate-submit"
          disabled={busy}
          data-testid="gate-submit"
        >
          Unlock
        </button>
      </form>
    </main>
  );
}

/** Lock / sign-out control for the top bar. Renders nothing outside a gate. */
export function LockButton() {
  const lock = useLock();
  if (!lock) return null;
  return (
    <button
      type="button"
      className="lock-button"
      onClick={lock}
      data-testid="lock-button"
      aria-label="Lock the app"
    >
      <span aria-hidden="true">🔒</span>
      <span className="lock-button-text">Lock</span>
    </button>
  );
}
