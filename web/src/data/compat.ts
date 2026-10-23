import { CONTRACT_MINOR, CONTRACT_VERSION } from "../contract/types";
import type { Meta } from "../contract/types";

/** Thrown when published data has a major version this app does not understand. The shell shows a refusal, not a broken page. */
export class ContractMajorError extends Error {
  constructor(readonly found: number) {
    super(`The published data is contract version ${found}; this app reads version ${CONTRACT_VERSION}.`);
    this.name = "ContractMajorError";
  }
}

/** Pass `meta` through, or refuse it when its major is not this app's (WEB-02). */
export function checkMajor(meta: Meta): Meta {
  const found: number = meta.contract_version;
  if (found !== CONTRACT_VERSION) throw new ContractMajorError(found);
  return meta;
}

/** True when the data predates the minor this app needs. Data without `contract_minor` is minor 0. */
export function isOlderMinor(meta: Meta): boolean {
  return (meta.contract_minor ?? 0) < CONTRACT_MINOR;
}
