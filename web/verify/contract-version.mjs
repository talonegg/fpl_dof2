import { readFileSync } from "node:fs";

const types = readFileSync(new URL("../src/contract/types.ts", import.meta.url), "utf8");

/** The contract major, read from the generated types so the verify scripts never restate it (WEB-02). */
export const CONTRACT_VERSION = Number(/export const CONTRACT_VERSION = (\d+);/.exec(types)?.[1]);
if (!Number.isInteger(CONTRACT_VERSION)) throw new Error("types.ts has no CONTRACT_VERSION");

/** The generated artefact registry (WEB-04): key -> {path, required, warm}. Emitted as JSON for this. */
export const ARTEFACTS = JSON.parse(/export const ARTEFACTS = (\{[\s\S]*?\r?\n\}) as const;/.exec(types)?.[1] ?? "null");
if (!ARTEFACTS) throw new Error("types.ts has no ARTEFACTS");
