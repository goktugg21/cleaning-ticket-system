import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Plus, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../../api/client";
import {
  createContractLine,
  createContractRevision,
  deleteContractLine,
  getContract,
  listContractRevisions,
} from "../../../api/contracts";
import type {
  Contract,
  ContractLine,
  ContractRevision,
  ContractStatus,
} from "../../../api/contracts.types";
import { BoundedList } from "../../../components/BoundedList";
import { ConfirmDialog } from "../../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../../components/ConfirmDialog";
import { EditModeToggle } from "../../../components/EditModeToggle";
import { useAuth } from "../../../auth/AuthContext";
import { canManageContracts } from "../../../auth/permissions";
import { useEditMode } from "../../../lib/useEditMode";
import { ContractFormDialog } from "./ContractFormDialog";
import { ContractInvoicePreview } from "./ContractInvoicePreview";
import { formatDate, formatMoney, formatNumber } from "./contractTables";

type Tab = "general" | "projects" | "billing" | "revisions";

const TABS: Tab[] = ["general", "projects", "billing", "revisions"];

// Contract statuses reuse the table's existing `cell-tag` vocabulary
// rather than a badge palette of their own. Same mapping as
// `ContractsAdminPage`; both read from the design system, so the two
// screens cannot show the same contract in different colours.
const STATUS_TAG: Record<ContractStatus, string> = {
  ACTIVE: "cell-tag-open",
  DRAFT: "cell-tag-muted",
  EXPIRED: "cell-tag-closed",
  CANCELLED: "cell-tag-rejected",
};

/**
 * Sprint 160 §4 — the contract detail page.
 *
 * Four tabs matching the reference: General Info, Projects, Billing
 * (which carries the Invoice Preview) and Revision History.
 *
 * The rule that shapes the Projects tab: **lines belong to a
 * REVISION.** Editing them means editing the revision currently in
 * force, and a revision whose effective date has arrived is closed —
 * so on a running contract the Projects tab is read-only and the way
 * to change a price is the "New revision" button on the Revision
 * History tab. That is not a limitation to work around; it is the
 * feature. If lines could be edited in place, last month's invoice
 * total would silently change when this month's price did.
 */
export function ContractDetailPage() {
  const { contractId } = useParams<{ contractId: string }>();
  const id = Number(contractId);
  const { t, i18n } = useTranslation("contracts");
  const { me } = useAuth();
  // The shared predicate, not an inline role list: a second copy of
  // "who may change commercial terms" is the drift CLAUDE.md warns about.
  const canManage = canManageContracts(me?.role);

  const [contract, setContract] = useState<Contract | null>(null);
  const [revisions, setRevisions] = useState<ContractRevision[]>([]);
  const [tab, setTab] = useState<Tab>("general");
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [revisionOpen, setRevisionOpen] = useState(false);
  const deleteLineRef = useRef<ConfirmDialogHandle>(null);
  const [lineToDelete, setLineToDelete] = useState<ContractLine | null>(null);

  // Derived rather than set in the effect body — see the note in
  // `ContractsAdminPage`. `reloadToken` is what Refresh and every
  // successful mutation bump, so there is ONE way to re-fetch.
  const requestKey = `${id}:${reloadToken}`;
  const loading = loadedKey !== requestKey;

  useEffect(() => {
    if (!Number.isFinite(id)) return;
    let cancelled = false;
    Promise.all([getContract(id), listContractRevisions(id)])
      .then(([detail, history]) => {
        if (cancelled) return;
        setContract(detail);
        setRevisions(history);
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
  }, [id, requestKey]);

  const reload = () => setReloadToken((current) => current + 1);

  const locale = i18n.language;
  const activeRevision =
    revisions.find((revision) => revision.is_active) ?? null;
  // The lines an operator may actually change: those of the active
  // revision, and only while that revision has not taken effect.
  const editableRevision =
    activeRevision && !activeRevision.is_locked ? activeRevision : null;
  const lines = activeRevision?.lines ?? [];

  const lineEdit = useEditMode<number>(
    editableRevision ? lines.map((line) => line.id) : [],
  );

  if (!Number.isFinite(id)) {
    return <div className="">{t("errors.notFound")}</div>;
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <nav className="eyebrow">
            <Link to="/admin/contracts">{t("list.title")}</Link>
          </nav>
          <h2 className="page-title">{contract?.contract_no ?? "…"}</h2>
          <p className="page-sub">
            {contract?.customer_name ?? ""}
            {contract && (
              <>
                {" · "}
                <span className={`cell-tag ${STATUS_TAG[contract.status]}`}>
                  {t(`status.${contract.status}`)}
                </span>
              </>
            )}
          </p>
        </div>
        <div className="page-header-actions">
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={reload}
            disabled={loading}
            data-testid="contract-refresh"
          >
            <RefreshCw size={16} strokeWidth={2} />
            {t("actions.refresh")}
          </button>
          {canManage && contract && (
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={() => setEditOpen(true)}
              data-testid="contract-edit"
            >
              {t("actions.editContract")}
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="alert-error" role="alert">
          {error}
        </div>
      )}

      {/* Header tiles — all four DERIVED from the active revision. */}
      <div className="summary-grid" data-testid="contract-tiles">
        <Tile
          label={t("tiles.monthly")}
          value={formatMoney(contract?.monthly_amount ?? "0", locale)}
        />
        <Tile
          label={t("tiles.yearly")}
          value={formatMoney(contract?.yearly_amount ?? "0", locale)}
        />
        <Tile
          label={t("tiles.hours")}
          value={formatNumber(contract?.total_hours ?? "0", locale)}
        />
        <Tile
          label={t("tiles.lineCount")}
          value={String(contract?.line_count ?? 0)}
        />
      </div>

      <div className="status-tabs" role="tablist" data-testid="contract-tabs">
        {TABS.map((key) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            className={tab === key ? "active" : ""}
            onClick={() => setTab(key)}
            data-testid={`contract-tab-${key}`}
          >
            {t(`tabs.${key}`)}
          </button>
        ))}
      </div>

      {tab === "general" && contract && (
        <section className="card" data-testid="contract-general">
          <dl className="contract-detail-grid">
            <Field label={t("fields.contractNo")} value={contract.contract_no} />
            <Field
              label={t("fields.customer")}
              value={
                <Link to={`/admin/customers/${contract.customer}`}>
                  {contract.customer_name ?? "—"}
                </Link>
              }
            />
            <Field
              label={t("fields.locations")}
              value={
                contract.buildings.length === 0 ? (
                  "—"
                ) : (
                  // Scrollable rather than unbounded: a contract can
                  // legitimately cover dozens of locations, and this is
                  // a SERVER collection (CLAUDE.md §8).
                  <BoundedList
                    size="sm"
                    count={contract.buildings.length}
                    ariaLabel={t("fields.locations")}
                    testIdPrefix="contract-locations"
                  >
                    <ul className="contract-plain-list">
                      {contract.buildings.map((building) => (
                        <li key={building.id}>
                          <Link to={`/admin/buildings/${building.id}`}>
                            {building.name}
                          </Link>
                        </li>
                      ))}
                    </ul>
                  </BoundedList>
                )
              }
            />
            <Field
              label={t("fields.type")}
              value={contract.contract_type_name ?? "—"}
            />
            <Field
              label={t("fields.status")}
              value={t(`status.${contract.status}`)}
            />
            <Field
              label={t("fields.startDate")}
              value={formatDate(contract.start_date, locale)}
            />
            <Field
              label={t("fields.endDate")}
              value={
                contract.end_date
                  ? formatDate(contract.end_date, locale)
                  : t("fields.openEnded")
              }
            />
            <Field
              label={t("fields.hoursPerYear")}
              value={formatNumber(
                Number(contract.total_hours) *
                  (contract.billing_period === "MONTHLY"
                    ? 12
                    : contract.billing_period === "QUARTERLY"
                      ? 4
                      : 1),
                locale,
              )}
            />
            <Field
              label={t("fields.description")}
              value={contract.description || "—"}
            />
            <Field label={t("fields.notes")} value={contract.notes || "—"} />
          </dl>
        </section>
      )}

      {tab === "projects" && (
        <section className="card" data-testid="contract-projects">
          <header className="section-head">
            <span className="section-head-title">{t("projects.title")}</span>
            {canManage && editableRevision && (
              <EditModeToggle
                editMode={lineEdit.editModeRequested}
                onToggle={lineEdit.toggleMode}
                testId="contract-lines-edit-toggle"
              />
            )}
          </header>

          {activeRevision && activeRevision.is_locked && (
            <p className="muted" data-testid="contract-lines-locked">
              {t("projects.lockedNotice", { label: activeRevision.label })}
            </p>
          )}

          <div className="table-wrap">
            <table className="data-table data-table-dense">
              <thead>
                <tr>
                  <th>{t("projects.name")}</th>
                  <th>{t("projects.building")}</th>
                  <th className="contract-num">{t("projects.hours")}</th>
                  <th className="contract-num">{t("projects.area")}</th>
                  <th className="contract-num">{t("projects.amount")}</th>
                  <th className="contract-num">{t("projects.vat")}</th>
                  {lineEdit.editMode && <th />}
                </tr>
              </thead>
              <tbody>
                {lines.map((line) => (
                  <tr key={line.id}>
                    <td>{line.name}</td>
                    <td>{line.building_name ?? "—"}</td>
                    <td className="contract-num">{formatNumber(line.hours, locale)}</td>
                    <td className="contract-num">
                      {line.area_m2 ? formatNumber(line.area_m2, locale) : "—"}
                    </td>
                    <td className="contract-num">{formatMoney(line.amount, locale)}</td>
                    <td className="contract-num">{formatNumber(line.vat_pct, locale)}%</td>
                    {lineEdit.editMode && (
                      <td>
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          onClick={() => {
                            setLineToDelete(line);
                            deleteLineRef.current?.open();
                          }}
                          data-testid={`contract-line-delete-${line.id}`}
                        >
                          {t("actions.remove")}
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
                {lines.length === 0 && (
                  <tr>
                    <td colSpan={7} className="muted">
                      {t("projects.empty")}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {canManage && editableRevision && (
            <AddLineForm
              revisionId={editableRevision.id}
              buildings={contract?.buildings ?? []}
              onAdded={reload}
              onError={(message) => setError(message)}
            />
          )}
        </section>
      )}

      {tab === "billing" && contract && (
        <section className="card" data-testid="contract-billing">
          <dl className="contract-detail-grid">
            <Field
              label={t("fields.billingPeriod")}
              value={t(`billingPeriod.${contract.billing_period}`)}
            />
            <Field
              label={t("fields.billingDay")}
              value={String(contract.billing_day)}
            />
            <Field
              label={t("fields.billingType")}
              value={t(`billingType.${contract.billing_type}`)}
            />
            <Field
              label={t("fields.paymentTerms")}
              value={t("fields.days", { count: contract.payment_terms_days })}
            />
            <Field
              label={t("fields.proration")}
              value={
                contract.start_proration ? t("fields.on") : t("fields.off")
              }
            />
          </dl>
          <ContractInvoicePreview contractId={contract.id} />
        </section>
      )}

      {tab === "revisions" && (
        <section className="card" data-testid="contract-revisions">
          <header className="section-head">
            <span className="section-head-title">{t("revisions.title")}</span>
            {canManage && (
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={() => setRevisionOpen(true)}
                data-testid="contract-new-revision"
              >
                <Plus size={16} strokeWidth={2} />
                {t("revisions.create")}
              </button>
            )}
          </header>

          {activeRevision && (
            <div className="summary-grid" data-testid="contract-current-status">
              <Tile
                label={t("revisions.activeRevision")}
                value={activeRevision.label}
              />
              <Tile
                label={t("revisions.effectiveSince")}
                value={formatDate(activeRevision.effective_from, locale)}
              />
              <Tile
                label={t("revisions.currentMonthly")}
                value={formatMoney(contract?.monthly_amount ?? "0", locale)}
              />
            </div>
          )}

          {revisions.length === 0 ? (
            <p className="muted" data-testid="contract-revisions-empty">
              {t("revisions.empty")}
            </p>
          ) : (
            <div className="table-wrap">
              <table className="data-table data-table-dense">
                <thead>
                  <tr>
                    <th>{t("revisions.label")}</th>
                    <th>{t("revisions.effectiveFrom")}</th>
                    <th className="contract-num">{t("revisions.amount")}</th>
                    <th className="contract-num">{t("revisions.lines")}</th>
                    <th>{t("revisions.author")}</th>
                    <th>{t("revisions.state")}</th>
                  </tr>
                </thead>
                <tbody>
                  {revisions.map((revision) => (
                    <tr key={revision.id}>
                      <td>{revision.label}</td>
                      <td>{formatDate(revision.effective_from, locale)}</td>
                      <td className="contract-num">
                        {formatMoney(revision.amount, locale)}
                      </td>
                      <td className="contract-num">{revision.line_count}</td>
                      <td>{revision.created_by_name ?? "—"}</td>
                      <td>
                        {revision.is_active && (
                          <span className="cell-tag cell-tag-open">
                            {t("revisions.isActive")}
                          </span>
                        )}
                        {!revision.is_active && revision.is_locked && (
                          <span className="cell-tag cell-tag-muted">
                            {t("revisions.isPast")}
                          </span>
                        )}
                        {!revision.is_locked && !revision.is_active && (
                          <span className="cell-tag cell-tag-normal">
                            {t("revisions.isPlanned")}
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      {/* Both dialogs render unconditionally and are driven through the
          ref — CLAUDE.md §3 / Sprint 128. */}
      <ConfirmDialog
        ref={deleteLineRef}
        title={t("projects.deleteTitle")}
        body={t("projects.deleteBody", { name: lineToDelete?.name ?? "" })}
        confirmLabel={t("actions.remove")}
        destructive
        busy={busy}
        onConfirm={() => {
          void (async () => {
            if (!lineToDelete) return;
            setBusy(true);
            try {
              await deleteContractLine(lineToDelete.id);
              deleteLineRef.current?.close();
              setLineToDelete(null);
              reload();
            } catch (err) {
              setError(getApiError(err));
              deleteLineRef.current?.close();
            } finally {
              setBusy(false);
            }
          })();
        }}
      />

      {contract && (
        <ContractFormDialog
          key={contract.id}
          open={editOpen}
          contract={contract}
          onClose={() => setEditOpen(false)}
          onSaved={() => {
            setEditOpen(false);
            reload();
          }}
        />
      )}

      <NewRevisionDialog
        open={revisionOpen}
        contractId={id}
        onClose={() => setRevisionOpen(false)}
        onCreated={() => {
          setRevisionOpen(false);
          reload();
        }}
      />
    </div>
  );
}

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="summary-stat">
      <span className="summary-stat-label">{label}</span>
      <span className="summary-stat-value">{value}</span>
    </div>
  );
}

function Field({
  label,
  value,
}: {
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="detail-field-row">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function AddLineForm({
  revisionId,
  buildings,
  onAdded,
  onError,
}: {
  revisionId: number;
  buildings: { id: number; name: string }[];
  onAdded: () => void;
  onError: (message: string) => void;
}) {
  const { t } = useTranslation("contracts");
  const [name, setName] = useState("");
  const [hours, setHours] = useState("0.00");
  const [amount, setAmount] = useState("0.00");
  const [area, setArea] = useState("");
  const [building, setBuilding] = useState<number | "">("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!name.trim()) return;
    setBusy(true);
    try {
      await createContractLine(revisionId, {
        name: name.trim(),
        hours,
        amount,
        area_m2: area || null,
        building: building === "" ? null : building,
      });
      setName("");
      setHours("0.00");
      setAmount("0.00");
      setArea("");
      setBuilding("");
      onAdded();
    } catch (err) {
      onError(getApiError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="contract-inline-form" data-testid="contract-add-line">
      <input
        className="field-input"
        placeholder={t("projects.name")}
        aria-label={t("projects.name")}
        value={name}
        onChange={(event) => setName(event.target.value)}
        data-testid="contract-line-name"
      />
      <select
        className="field-input"
        aria-label={t("projects.building")}
        value={building}
        onChange={(event) =>
          setBuilding(
            event.target.value === "" ? "" : Number(event.target.value),
          )
        }
        data-testid="contract-line-building"
      >
        <option value="">{t("projects.wholeContract")}</option>
        {buildings.map((row) => (
          <option key={row.id} value={row.id}>
            {row.name}
          </option>
        ))}
      </select>
      <input
        className="field-input"
        type="number"
        step="0.01"
        aria-label={t("projects.hours")}
        value={hours}
        onChange={(event) => setHours(event.target.value)}
        data-testid="contract-line-hours"
      />
      <input
        className="field-input"
        type="number"
        step="0.01"
        aria-label={t("projects.area")}
        placeholder={t("projects.area")}
        value={area}
        onChange={(event) => setArea(event.target.value)}
        data-testid="contract-line-area"
      />
      <input
        className="field-input"
        type="number"
        step="0.01"
        aria-label={t("projects.amount")}
        value={amount}
        onChange={(event) => setAmount(event.target.value)}
        data-testid="contract-line-amount"
      />
      <button
        type="button"
        className="btn btn-primary btn-sm"
        onClick={() => void submit()}
        disabled={busy || !name.trim()}
        data-testid="contract-line-add"
      >
        {t("projects.add")}
      </button>
    </div>
  );
}

function NewRevisionDialog({
  open,
  contractId,
  onClose,
  onCreated,
}: {
  open: boolean;
  contractId: number;
  onClose: () => void;
  onCreated: () => void;
}) {
  const { t } = useTranslation("contracts");
  const [label, setLabel] = useState("");
  const [effectiveFrom, setEffectiveFrom] = useState("");
  const [copyLines, setCopyLines] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  if (!open) return null;

  const submit = async () => {
    if (!label.trim() || !effectiveFrom) {
      setError(t("revisions.labelAndDateRequired"));
      return;
    }
    setBusy(true);
    setError("");
    try {
      await createContractRevision(contractId, {
        label: label.trim(),
        effective_from: effectiveFrom,
        copy_lines: copyLines,
      });
      setLabel("");
      setEffectiveFrom("");
      onCreated();
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={t("revisions.create")}
      data-testid="contract-revision-dialog"
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.4)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 100,
        padding: 16,
      }}
    >
      <div
        className="card"
        style={{ maxWidth: 480, width: "100%", padding: 24 }}
      >
        <h2>{t("revisions.create")}</h2>
        <p className="muted">{t("revisions.createHint")}</p>

        {error && (
          <div className="alert-error" role="alert">
            {error}
          </div>
        )}

        <label className="field">
          <span className="field-label">{t("revisions.label")}</span>
          <input
            className="field-input"
            value={label}
            onChange={(event) => setLabel(event.target.value)}
            data-testid="contract-revision-label"
          />
        </label>
        <label className="field">
          <span className="field-label">{t("revisions.effectiveFrom")}</span>
          <input
            className="field-input"
            type="date"
            value={effectiveFrom}
            onChange={(event) => setEffectiveFrom(event.target.value)}
            data-testid="contract-revision-date"
          />
          <span className="muted small">{t("revisions.effectiveHint")}</span>
        </label>
        <label className="entity-picker-row" htmlFor="contract-revision-copy">
          <input
            id="contract-revision-copy"
            type="checkbox"
            checked={copyLines}
            onChange={(event) => setCopyLines(event.target.checked)}
            data-testid="contract-revision-copy"
          />
          <span className="entity-picker-text">{t("revisions.copyLines")}</span>
        </label>

        <div className="filter-actions" style={{ justifyContent: "flex-end" }}>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={onClose}
            disabled={busy}
          >
            {t("actions.cancel")}
          </button>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={() => void submit()}
            disabled={busy}
            data-testid="contract-revision-save"
          >
            {busy ? t("actions.saving") : t("actions.save")}
          </button>
        </div>
      </div>
    </div>
  );
}
