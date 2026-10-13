/** Lowercase hex, trimmed: the one form both the build-time hash and a computed hash compare in. */
export function normaliseHash(value: string | undefined | null): string {
  return (value ?? "").trim().toLowerCase();
}

/** SHA-256 of the UTF-8 password via WebCrypto, as lowercase hex. */
export async function sha256Hex(text: string): Promise<string> {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(text),
  );
  return Array.from(new Uint8Array(digest), (b) =>
    b.toString(16).padStart(2, "0"),
  ).join("");
}

/** The hash injected at build time from `VITE_FPL_PASSWORD_HASH` (deploy.yml ← secret FPL_PASSWORD_HASH). */
export const BUILD_PASSWORD_HASH = normaliseHash(
  import.meta.env.VITE_FPL_PASSWORD_HASH as string | undefined,
);

/** localStorage key. Holds the hash that was unlocked, never the password. */
export const UNLOCK_KEY = "fpl-dof:unlocked-hash";
