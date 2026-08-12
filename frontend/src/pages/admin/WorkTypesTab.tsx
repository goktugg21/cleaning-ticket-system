import { useCallback } from "react";
import { useTranslation } from "react-i18next";

import { CatalogTab } from "../../components/CatalogTab";
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
 * It sits on /admin/hours beside Hour types, because a work type is an
 * hours concept and that is where an operator managing hour types is
 * already standing.
 */
export function WorkTypesTab() {
  const { t } = useTranslation("common");

  const mapRow = useCallback(
    (raw: Record<string, unknown>): CatalogRow => ({
      id: raw.id as number,
      name: raw.name as string,
      is_active: raw.is_active as boolean,
      usage: (raw.usage_count as number) ?? 0,
    }),
    [],
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
