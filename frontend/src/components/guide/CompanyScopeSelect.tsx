/**
 * P-12 §D.24.2 — the Finance pages' Company selector, top right,
 * SUPER_ADMIN only. Renders nothing with one company (the
 * CatalogCompanySelect stance: no control for no choice). There is no
 * "all companies" option — one company at a time is the point.
 */
import { useTranslation } from "react-i18next";

import type { CompanyAdmin } from "../../api/types";
import "./guide.css";

export function CompanyScopeSelect({
  companies,
  companyId,
  onChange,
  testId = "guide-company-scope",
}: {
  companies: CompanyAdmin[];
  companyId: number | "";
  onChange: (id: number) => void;
  testId?: string;
}) {
  const { t } = useTranslation("common");
  if (companies.length <= 1) return null;
  return (
    <label className="guide-company">
      <span className="guide-company-label">{t("guide.company")}</span>
      <select
        className="filter-control"
        value={companyId}
        onChange={(event) => {
          const id = Number(event.target.value);
          if (Number.isInteger(id) && id > 0) onChange(id);
        }}
        data-testid={testId}
      >
        {companyId === "" && <option value="">…</option>}
        {companies.map((company) => (
          <option key={company.id} value={company.id}>
            {company.name}
          </option>
        ))}
      </select>
    </label>
  );
}
