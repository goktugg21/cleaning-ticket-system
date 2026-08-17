import { useCallback } from "react";
import { useTranslation } from "react-i18next";

import { CatalogTab } from "../../../components/CatalogTab";
import { contractTypeLabel } from "../../../lib/contractTypeLabel";
import type { CatalogRow } from "../../../components/CatalogTab";

/**
 * Sprint 168 §5 — the contract-type catalog, managed.
 *
 * A new company starts with an empty catalog and the type field on a
 * contract is required, so without this screen a new tenant cannot
 * create a single contract. Sprint 166 recorded that gap.
 *
 * Sprint 169 §2 moved the SHAPE into `CatalogTab`: work types needed
 * the identical screen, and writing the second one as a copy of this
 * file is the drift CLAUDE.md names — the same sprint's §8 exists
 * because two copies of a list were left to drift for six sprints.
 * What stays here is what genuinely differs: the endpoints and the
 * words.
 */
export function ContractTypesTab() {
  const { t } = useTranslation(["contracts", "common"]);

  const mapRow = useCallback(
    (raw: Record<string, unknown>): CatalogRow => ({
      id: raw.id as number,
      name: raw.name as string,
      // Sprint 170 §5 — the same treatment as work types: the table
      // shows the reader's language, Rename edits the stored name.
      displayName: contractTypeLabel(
        raw.name as string,
        (raw.standard_slot as string) ?? "",
        t,
      ),
      is_active: raw.is_active as boolean,
      usage: (raw.contract_count as number) ?? 0,
    }),
    [t],
  );

  return (
    <CatalogTab
      listUrl="/contracts/types/"
      detailUrl={(id) => `/contracts/types/${id}/`}
      standardSetUrl="/contracts/types/standard-set/"
      testIdPrefix="contract-types"
      mapRow={mapRow}
      labels={{
        title: t("types.title"),
        desc: t("types.desc"),
        standardSet: t("types.standardSet"),
        name: t("types.name"),
        inUse: t("types.inUse"),
        state: t("types.state"),
        actions: t("common:contract_hours.actions"),
        active: t("types.active"),
        archived: t("types.archived"),
        archive: t("types.archive"),
        reactivate: t("types.reactivate"),
        delete: t("common:contract_hours.delete"),
        empty: t("types.empty"),
        newName: t("types.newName"),
        newPlaceholder: t("types.newPlaceholder"),
        add: t("types.add"),
        rename: t("types.rename"),
        save: t("common:hours_week_grid.save"),
        cancel: t("common:cancel"),
      }}
    />
  );
}
