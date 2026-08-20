import { useCallback } from "react";
import { useTranslation } from "react-i18next";

import { CatalogTab } from "../../components/CatalogTab";
import { workTypeLabel } from "../../lib/workTypeLabel";
import type { CatalogRow } from "../../components/CatalogTab";

/**
 * Sprint 169 §2 — the work-type catalog, managed.
 *
 * Sprint 168 built the model, the endpoints (`work-types/`,
 * `work-types/<id>/`, `work-types/standard-set/`) and the column, and
 * no screen. The frontend never called any of them: the Work type
 * dropdown was empty everywhere and there was nothing anywhere that
 * could put a row in it. The same defect as contract types, one screen
 * over, and it should have been caught by the same reasoning.
 *
 * W7 §2 — it is now called "Contract work types" on screen, and on
 * /admin/hours it sits under "Agreed in a contract" rather than beside
 * Hour types.
 *
 * Two reasons, and the second is the one that matters. `ContractHours`
 * is the ONLY consumer of `timesheets.WorkType` — grep the FK — so
 * "contract work type" is what the row has always been. And "Work type"
 * was already taken: `customers.WorkType` is a per-CUSTOMER label on an
 * Extra Work request (Eindschoonmaak, Bouw schoonmaak), a different
 * table with a different owner and a different consumer, and it is the
 * one an operator meets daily on the Extra Work screens. Two unrelated
 * things could not both keep the name, so the rarer one gave it up.
 * `customers.WorkType` is untouched.
 */
export function WorkTypesTab() {
  const { t } = useTranslation("common");

  const mapRow = useCallback(
    (raw: Record<string, unknown>): CatalogRow => ({
      id: raw.id as number,
      name: raw.name as string,
      // Sprint 170 §5 — a recognised standard kind renders in the
      // reader's language; a company's own name renders verbatim. The
      // STORED name above is what Rename edits.
      displayName: workTypeLabel(
        raw.name as string,
        (raw.standard_slot as string) ?? "",
        t,
      ),
      is_active: raw.is_active as boolean,
      usage: (raw.usage_count as number) ?? 0,
    }),
    [t],
  );

  return (
    <CatalogTab
      listUrl="/timesheets/work-types/"
      detailUrl={(id) => `/timesheets/work-types/${id}/`}
      standardSetUrl="/timesheets/work-types/standard-set/"
      testIdPrefix="work-types"
      mapRow={mapRow}
      labels={{
        title: t("work_types.title"),
        desc: t("work_types.desc"),
        standardSet: t("work_types.standard_set"),
        name: t("work_types.name"),
        inUse: t("work_types.in_use"),
        state: t("status"),
        actions: t("contract_hours.actions"),
        active: t("work_types.active"),
        archived: t("work_types.archived"),
        archive: t("work_types.archive"),
        reactivate: t("work_types.reactivate"),
        delete: t("contract_hours.delete"),
        empty: t("work_types.empty"),
        newName: t("work_types.new_name"),
        newPlaceholder: t("work_types.new_placeholder"),
        add: t("work_types.add"),
        rename: t("work_types.rename"),
        save: t("hours_week_grid.save"),
        cancel: t("cancel"),
      }}
    />
  );
}
