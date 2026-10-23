import { readFileSync } from "node:fs";

/** The contract major, read from the generated types so the verify scripts never restate it (WEB-02). */
export const CONTRACT_VERSION = Number(
  /export const CONTRACT_VERSION = (\d+);/.exec(
    readFileSync(new URL("../src/contract/types.ts", import.meta.url), "utf8"),
  )?.[1],
);
if (!Number.isInteger(CONTRACT_VERSION)) throw new Error("types.ts has no CONTRACT_VERSION");
