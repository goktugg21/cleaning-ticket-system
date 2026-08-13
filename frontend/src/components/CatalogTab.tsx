import { useEffect, useState } from "react";
import { Plus } from "lucide-react";

import { listAllCompanies } from "../api/admin";
import { api, getApiError } from "../api/client";
import type { CompanyAdmin } from "../api/types";

export interface CatalogRow {
  id: number;
  /** The STORED name — what a rename starts from and writes back. */
  name: string;
  /** What the table SHOWS. Differs from `name` only for a recognised
   *  standard kind, which renders in the reader's language.
   *
   *  Sprint 170 §5 — kept separate deliberately. Seeding the rename
   *  field from the translated label would mean an operator who opened
   *  Rename in English, changed nothing and pressed Save silently
   *  rewrote a Dutch-seeded row's stored name to English. */
  displayName?: string;
  is_active: boolean;
  /** How many things point at this row. Non-zero means Delete is not
   *  offerable, because every one of these catalogs is referenced by a
   *  PROTECT foreign key. */
  usage: number;
}

export interface CatalogLabels {
  title: string;
  desc: string;
  /** Only read when `standardSetUrl` is supplied. */
  standardSet: string;
  name: string;
  inUse: string;
  state: string;
  actions: string;
  active: string;
  archived: string;
  archive: string;
  reactivate: string;
  delete: string;
  empty: string;
  newName: string;
  newPlaceholder: string;
  add: string;
  rename: string;
  save: string;
  cancel: string;
}

/**
 * Sprint 169 §2 — ONE per-company catalog screen, used by both.
 *
 * Contract types (Sprint 168 §5) and work types (this sprint) are the
 * same screen over different endpoints: a per-company list, add,
 * rename, archive, delete-when-unused, and one button that offers the
 * standard set to a company that has none. Writing the second one as a
 * copy of the first is precisely the drift CLAUDE.md names — and the
 * same sprint's §8 exists because two copies of a list were left to
 * drift for six sprints. So the shape lives here once and each catalog
 * passes its endpoints and its own words.
 *
 * What is deliberately NOT generic: the four seeded names, the
 * permission gate, and the i18n namespace. Those genuinely differ, and
 * a component that tried to own them would need a flag per caller.
 *
 * The company selector appears only when the deployment has more than
 * one provider company. It has to exist at all because these catalogs
 * are per-company and a WRITE must name one — without it a SUPER_ADMIN
 * gets `company is required when more than one provider Company
 * exists`, which is exactly how the contract-types button failed the
 * first time it was pressed.
 */
export function CatalogTab({
  listUrl,
  detailUrl,
  standardSetUrl,
  labels,
  mapRow,
  testIdPrefix,
  canManage = true,
}: {
  listUrl: string;
  detailUrl: (id: number) => string;
  /** Sprint 178 §1 — OPTIONAL. Most catalogs ship a recognised standard
   *  set an operator can seed in one click; some are bespoke by nature
   *  (a building type like "health building" is the owner's own example
   *  of a type only one company will ever want). Omitted, the seed
   *  button is simply not rendered — a button that posts to nowhere is
   *  worse than no button. */
  standardSetUrl?: string;
  labels: CatalogLabels;
  /** Each catalog names its usage count differently
   *  (`contract_count` / `usage_count`), so the caller maps. */
  mapRow: (raw: Record<string, unknown>) => CatalogRow;
  testIdPrefix: string;
  canManage?: boolean;
}) {
  const [companies, setCompanies] = useState<CompanyAdmin[]>([]);
  const [companyId, setCompanyId] = useState<number | "">("");
  const [rows, setRows] = useState<CatalogRow[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [newName, setNewName] = useState("");
  const [renaming, setRenaming] = useState<number | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [reloadKey, setReloadKey] = useState(0);

  const requestKey = `${companyId}:${reloadKey}`;
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const loading = loadedKey !== requestKey;

  useEffect(() => {
    let cancelled = false;
    listAllCompanies()
      .then((all) => {
        if (cancelled) return;
        setCompanies(all);
        // Seeded inside the .then(), never in an effect body. The
        // LOWEST id is the deployment's first tenant, not an
        // alphabetical accident.
        setCompanyId((current) =>
          current === "" && all.length > 0
            ? [...all].sort((a, b) => a.id - b.id)[0].id
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
      .get(listUrl, { params: { company: companyId || undefined } })
      .then((response) => {
        if (cancelled) return;
        const raw = (response.data.results ?? response.data) as Record<
          string,
          unknown
        >[];
        setRows(raw.map(mapRow));
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
  }, [companyId, requestKey, listUrl, mapRow]);

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
    <section
      className="card card-detail-pad"
      data-testid={`${testIdPrefix}-tab`}
    >
      <header className="section-head">
        <div>
          <div className="section-head-title">{labels.title}</div>
          <div className="section-head-sub">{labels.desc}</div>
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
            data-testid={`${testIdPrefix}-company`}
          >
            {companies.map((company) => (
              <option key={company.id} value={company.id}>
                {company.name}
              </option>
            ))}
          </select>
        )}
        {canManage && standardSetUrl && (
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() =>
              void run(() =>
                api.post(standardSetUrl, { company: companyId || undefined }),
              )
            }
            disabled={busy}
            data-testid={`${testIdPrefix}-standard-set`}
          >
            {labels.standardSet}
          </button>
        )}
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
              <th>{labels.name}</th>
              <th className="contract-num">{labels.inUse}</th>
              <th>{labels.state}</th>
              {canManage && <th>{labels.actions}</th>}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} data-testid={`${testIdPrefix}-row-${row.id}`}>
                <td className="td-subject">
                  {renaming === row.id ? (
                    <input
                      className="field-input"
                      value={renameValue}
                      onChange={(event) => setRenameValue(event.target.value)}
                      aria-label={labels.rename}
                      data-testid={`${testIdPrefix}-rename-input-${row.id}`}
                    />
                  ) : (
                    (row.displayName ?? row.name)
                  )}
                </td>
                <td className="contract-num">{row.usage}</td>
                <td>
                  <span
                    className={`cell-tag ${
                      row.is_active ? "cell-tag-open" : "cell-tag-muted"
                    }`}
                  >
                    {row.is_active ? labels.active : labels.archived}
                  </span>
                </td>
                {canManage && (
                  <td>
                    <div style={{ display: "flex", gap: 6 }}>
                      {renaming === row.id ? (
                        <>
                          <button
                            type="button"
                            className="btn btn-primary btn-sm"
                            onClick={() =>
                              void run(async () => {
                                await api.patch(detailUrl(row.id), {
                                  name: renameValue.trim(),
                                });
                                setRenaming(null);
                              })
                            }
                            disabled={busy || !renameValue.trim()}
                            data-testid={`${testIdPrefix}-rename-save-${row.id}`}
                          >
                            {labels.save}
                          </button>
                          <button
                            type="button"
                            className="btn btn-ghost btn-sm"
                            onClick={() => setRenaming(null)}
                            disabled={busy}
                          >
                            {labels.cancel}
                          </button>
                        </>
                      ) : (
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          onClick={() => {
                            setRenaming(row.id);
                            setRenameValue(row.name);
                          }}
                          disabled={busy}
                          data-testid={`${testIdPrefix}-rename-${row.id}`}
                        >
                          {labels.rename}
                        </button>
                      )}
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        onClick={() =>
                          void run(() =>
                            api.patch(detailUrl(row.id), {
                              is_active: !row.is_active,
                            }),
                          )
                        }
                        disabled={busy}
                        data-testid={`${testIdPrefix}-archive-${row.id}`}
                      >
                        {row.is_active ? labels.archive : labels.reactivate}
                      </button>
                      {/* Offered only when nothing points at it: the FK
                          is PROTECT, so a used row can never be deleted
                          and a button that always 409s is worse than no
                          button. Archive is the route for one in use. */}
                      {row.usage === 0 && (
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          onClick={() =>
                            void run(() => api.delete(detailUrl(row.id)))
                          }
                          disabled={busy}
                          data-testid={`${testIdPrefix}-delete-${row.id}`}
                        >
                          {labels.delete}
                        </button>
                      )}
                    </div>
                  </td>
                )}
              </tr>
            ))}
            {!loading && rows.length === 0 && (
              <tr>
                <td colSpan={canManage ? 4 : 3} className="muted">
                  {labels.empty}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {canManage && (
        <form
          className="filter-bar"
          style={{ marginTop: 12 }}
          onSubmit={(event) => {
            event.preventDefault();
            if (!newName.trim()) return;
            void run(async () => {
              await api.post(listUrl, {
                company: companyId || undefined,
                name: newName.trim(),
              });
              setNewName("");
            });
          }}
        >
          <div className="filter-field">
            <span className="filter-label">{labels.newName}</span>
            <input
              className="filter-control"
              value={newName}
              onChange={(event) => setNewName(event.target.value)}
              placeholder={labels.newPlaceholder}
              data-testid={`${testIdPrefix}-new-name`}
            />
          </div>
          <div className="filter-actions">
            <button
              type="submit"
              className="btn btn-primary btn-sm"
              disabled={busy || !newName.trim()}
              data-testid={`${testIdPrefix}-add`}
            >
              <Plus size={14} strokeWidth={2.5} />
              {labels.add}
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
