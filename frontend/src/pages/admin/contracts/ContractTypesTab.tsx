import { useEffect, useState } from "react";
import { Plus } from "lucide-react";
import { useTranslation } from "react-i18next";

import { listAllCompanies } from "../../../api/admin";
import { api, getApiError } from "../../../api/client";
import type { CompanyAdmin } from "../../../api/types";

interface ContractTypeRow {
  id: number;
  name: string;
  is_active: boolean;
  sort_order: number;
  contract_count: number;
}

/**
 * Sprint 168 §5 — the contract-type catalog, managed.
 *
 * The catalog was per-company from the start and that was the right
 * call: the reference shows "Cleaning" and "Machine" and the next
 * tenant will have others. What was missing is the consequence — a NEW
 * company starts with an empty catalog, the type field on a contract is
 * required, and so a new tenant cannot create a single contract until
 * somebody puts rows in a table they have no screen for. Sprint 166
 * recorded that gap; this closes it.
 *
 * The four reference kinds are OFFERED through one button, the shape
 * the hour-type catalog already uses. Offered, not imposed: they are
 * ordinary rows and a company may rename or delete every one.
 *
 * A type in use is not deletable — `Contract.contract_type` is PROTECT
 * — so the row shows its usage count and offers Archive instead, which
 * removes it from the pickers for NEW contracts while every existing
 * contract keeps reading exactly as it did.
 */
export function ContractTypesTab() {
  const { t } = useTranslation(["contracts", "common"]);
  // The catalog is PER COMPANY, so this screen has to say which one.
  // The contracts list does not ask (it is already scoped to the
  // actor), but a WRITE here must name its company or a SUPER_ADMIN in
  // a multi-company deployment gets `contract_company_required` — which
  // is exactly what the standard-set button did before this existed.
  const [companies, setCompanies] = useState<CompanyAdmin[]>([]);
  const [companyId, setCompanyId] = useState<number | "">("");
  const [rows, setRows] = useState<ContractTypeRow[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [newName, setNewName] = useState("");
  const [reloadKey, setReloadKey] = useState(0);

  const requestKey = `${companyId}:${reloadKey}`;
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const loading = loadedKey !== requestKey;

  useEffect(() => {
    let cancelled = false;
    listAllCompanies()
      .then((rows) => {
        if (cancelled) return;
        setCompanies(rows);
        // Seeded inside the .then(), never in an effect body — a
        // synchronous setState there is banned. The LOWEST id is the
        // deployment's first tenant, not an alphabetical accident.
        setCompanyId((current) =>
          current === "" && rows.length > 0
            ? [...rows].sort((a, b) => a.id - b.id)[0].id
            : current,
        );
      })
      .catch(() => {
        if (!cancelled) setCompanies([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    api
      .get("/contracts/types/", {
        params: { company: companyId || undefined },
      })
      .then((response) => {
        if (cancelled) return;
        setRows(response.data.results ?? response.data);
        setError("");
      })
      .catch((err) => {
        if (!cancelled) setError(getApiError(err));
      })
      .finally(() => {
        if (!cancelled) setLoadedKey(requestKey);
      });
    return () => {
      cancelled = true;
    };
  }, [companyId, requestKey]);

  async function run(work: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await work();
      setReloadKey((n) => n + 1);
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card card-detail-pad" data-testid="contract-types-tab">
      <header className="section-head">
        <div>
          <div className="section-head-title">{t("types.title")}</div>
          <div className="section-head-sub">{t("types.desc")}</div>
        </div>
        {companies.length > 1 && (
          <select
            className="filter-control"
            value={companyId}
            onChange={(event) =>
              setCompanyId(
                event.target.value === "" ? "" : Number(event.target.value),
              )
            }
            data-testid="contract-types-company"
          >
            {companies.map((company) => (
              <option key={company.id} value={company.id}>
                {company.name}
              </option>
            ))}
          </select>
        )}
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          onClick={() =>
            void run(() =>
              api.post("/contracts/types/standard-set/", {
                company: companyId || undefined,
              }),
            )
          }
          disabled={busy}
          data-testid="contract-types-standard-set"
        >
          {t("types.standardSet")}
        </button>
      </header>

      {error && (
        <div className="alert-error" style={{ marginBottom: 12 }} role="alert">
          {error}
        </div>
      )}

      {loading && (
        <div className="loading-bar" style={{ margin: 0 }}>
          <div className="loading-bar-fill" />
        </div>
      )}

      <div className="table-wrap">
        <table className="data-table data-table-dense">
          <thead>
            <tr>
              <th>{t("types.name")}</th>
              <th className="contract-num">{t("types.inUse")}</th>
              <th>{t("types.state")}</th>
              <th>{t("common:contract_hours.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} data-testid={`contract-type-row-${row.id}`}>
                <td className="td-subject">{row.name}</td>
                <td className="contract-num">{row.contract_count}</td>
                <td>
                  <span
                    className={`cell-tag ${
                      row.is_active ? "cell-tag-open" : "cell-tag-muted"
                    }`}
                  >
                    {row.is_active ? t("types.active") : t("types.archived")}
                  </span>
                </td>
                <td>
                  <div style={{ display: "flex", gap: 6 }}>
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      onClick={() =>
                        void run(() =>
                          api.patch(`/contracts/types/${row.id}/`, {
                            is_active: !row.is_active,
                          }),
                        )
                      }
                      disabled={busy}
                      data-testid={`contract-type-archive-${row.id}`}
                    >
                      {row.is_active
                        ? t("types.archive")
                        : t("types.reactivate")}
                    </button>
                    {/* Offered only when nothing points at it: the FK is
                        PROTECT, so a used type can never be deleted and
                        a button that always 409s is worse than none. */}
                    {row.contract_count === 0 && (
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        onClick={() =>
                          void run(() =>
                            api.delete(`/contracts/types/${row.id}/`),
                          )
                        }
                        disabled={busy}
                        data-testid={`contract-type-delete-${row.id}`}
                      >
                        {t("common:contract_hours.delete")}
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
            {!loading && rows.length === 0 && (
              <tr>
                <td colSpan={4} className="muted">
                  {t("types.empty")}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <form
        className="filter-bar"
        style={{ marginTop: 12 }}
        onSubmit={(event) => {
          event.preventDefault();
          if (!newName.trim()) return;
          void run(async () => {
            await api.post("/contracts/types/", {
              company: companyId || undefined,
              name: newName.trim(),
            });
            setNewName("");
          });
        }}
      >
        <div className="filter-field">
          <span className="filter-label">{t("types.newName")}</span>
          <input
            className="filter-control"
            value={newName}
            onChange={(event) => setNewName(event.target.value)}
            placeholder={t("types.newPlaceholder")}
            data-testid="contract-type-new-name"
          />
        </div>
        <div className="filter-actions">
          <button
            type="submit"
            className="btn btn-primary btn-sm"
            disabled={busy || !newName.trim()}
            data-testid="contract-type-add"
          >
            <Plus size={14} strokeWidth={2.5} />
            {t("types.add")}
          </button>
        </div>
      </form>
    </section>
  );
}
