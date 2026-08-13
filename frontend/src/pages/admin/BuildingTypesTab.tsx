import { useCallback } from "react";
import { useTranslation } from "react-i18next";

import { CatalogTab } from "../../components/CatalogTab";
import type { CatalogRow } from "../../components/CatalogTab";

/**
 * Sprint 178 §1 — the building-type catalog, managed.
 *
 * This is the proof that the catalog MECHANISM works, and it is the
 * owner's own example:
 *
 *     Ramazan may want one building to be of type "health building" even
 *     though no other building uses it — but it should still appear in
 *     the filters.
 *
 * The whole tab is this file: a `CatalogTab` with three URLs and its
 * labels. That is the point — the shape lives in `CatalogTab` (Sprint
 * 169) and a new catalog is a thin wrapper over it, not a new page.
 *
 * **No `standardSetUrl`.** Hour types and work types have recognised
 * standard kinds worth seeding in one click; a building type is bespoke
 * by nature, which is precisely what the owner's example says. Sprint 178
 * made the prop optional rather than inventing a "standard" list of
 * building kinds nobody asked for — the seed button simply is not
 * rendered.
 */
export function BuildingTypesTab() {
  const { t } = useTranslation("common");

  const mapRow = useCallback(
    (raw: Record<string, unknown>): CatalogRow => ({
      id: raw.id as number,
      name: raw.name as string,
      // No `displayName`: unlike hour types there is no standard slot to
      // translate, so the stored name IS the display name. A company's
      // own word for its own building kind should not be second-guessed.
      is_active: raw.is_active as boolean,
      usage: (raw.usage_count as number) ?? 0,
    }),
    [],
  );

  return (
    <CatalogTab
      listUrl="/buildings/types/"
      detailUrl={(id) => `/buildings/types/${id}/`}
      testIdPrefix="building-types"
      mapRow={mapRow}
      labels={{
        title: t("building_types.title"),
        desc: t("building_types.desc"),
        // Read only when `standardSetUrl` is supplied, which it is not.
        standardSet: "",
        name: t("building_types.name"),
        inUse: t("building_types.in_use"),
        state: t("status"),
        actions: t("contract_hours.actions"),
        active: t("building_types.active"),
        archived: t("building_types.archived"),
        archive: t("building_types.archive"),
        reactivate: t("building_types.reactivate"),
        delete: t("contract_hours.delete"),
        empty: t("building_types.empty"),
        newName: t("building_types.new_name"),
        newPlaceholder: t("building_types.new_placeholder"),
        add: t("building_types.add"),
        rename: t("building_types.rename"),
        save: t("hours_week_grid.save"),
        cancel: t("cancel"),
      }}
    />
  );
}
