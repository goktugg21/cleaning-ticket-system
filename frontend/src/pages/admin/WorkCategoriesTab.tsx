import { useCallback } from "react";
import { useTranslation } from "react-i18next";

import { CatalogTab } from "../../components/CatalogTab";
import type { CatalogRow } from "../../components/CatalogTab";

/**
 * Sprint 185 E §1 — the work-category catalog, managed.
 *
 * The kinds of WORK a company distinguishes — sanitair, glasbewassing,
 * vloeren, afval — beside the kind of MESSAGE `Ticket.type` already
 * holds. The monthly customer review is "how many meldingen per category
 * per building", and before this sprint no tenant could add a category
 * without a developer.
 *
 * The whole tab is this file: a `CatalogTab` with three URLs and its
 * labels. That is the point — the shape lives in `CatalogTab` (Sprint
 * 169) and a new catalog is a thin wrapper over it, not a new page.
 *
 * **No `standardSetUrl`.** Hour types and work types have recognised
 * standard kinds worth seeding in one click; the trades a cleaning
 * company distinguishes are its own vocabulary, which is the whole
 * reason this is a catalog rather than an enum. The seed button is
 * simply not rendered.
 */
export function WorkCategoriesTab() {
  const { t } = useTranslation("common");

  const mapRow = useCallback(
    (raw: Record<string, unknown>): CatalogRow => ({
      id: raw.id as number,
      name: raw.name as string,
      // No `displayName`: there is no standard slot to translate, so the
      // stored name IS the display name. A company's own word for its
      // own trade should not be second-guessed.
      is_active: raw.is_active as boolean,
      usage: (raw.usage_count as number) ?? 0,
    }),
    [],
  );

  return (
    <CatalogTab
      listUrl="/tickets/categories/"
      detailUrl={(id) => `/tickets/categories/${id}/`}
      testIdPrefix="work-categories"
      mapRow={mapRow}
      labels={{
        title: t("work_categories.title"),
        desc: t("work_categories.desc"),
        // Read only when `standardSetUrl` is supplied, which it is not.
        standardSet: "",
        name: t("work_categories.name"),
        inUse: t("work_categories.in_use"),
        state: t("status"),
        actions: t("contract_hours.actions"),
        active: t("work_categories.active"),
        archived: t("work_categories.archived"),
        archive: t("work_categories.archive"),
        reactivate: t("work_categories.reactivate"),
        delete: t("contract_hours.delete"),
        empty: t("work_categories.empty"),
        // Sprint 179B §1 — the catalog whose control has not appeared
        // yet explains itself. Until a category exists there is no
        // Category filter on the meldingen list and no report to read,
        // so the empty state is the only screen that can say so.
        emptyHint: t("work_categories.empty_hint"),
        newName: t("work_categories.new_name"),
        newPlaceholder: t("work_categories.new_placeholder"),
        add: t("work_categories.add"),
        rename: t("work_categories.rename"),
        save: t("hours_week_grid.save"),
        cancel: t("cancel"),
      }}
    />
  );
}
