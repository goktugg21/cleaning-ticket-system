// W-UX F51 — ONE map from a contract status to its `.cell-tag` tone.
//
// Three pages carried an identical private copy (the contracts admin
// list, the contract detail page, the customer's contracts page). Three
// copies of a four-line map is the drift CLAUDE.md names: a fifth status
// added to one and forgotten in another renders an unstyled tag on that
// page only. One exported constant, three importers.
import type { ContractStatus } from "../api/contracts.types";

export const CONTRACT_STATUS_TAG: Readonly<Record<ContractStatus, string>> = {
  ACTIVE: "cell-tag-open",
  DRAFT: "cell-tag-muted",
  EXPIRED: "cell-tag-closed",
  CANCELLED: "cell-tag-rejected",
};
