import { Fragment, useEffect, useMemo, useRef, useState } from "react";
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
  updateContract,
} from "../../../api/contracts";
import type {
  Contract,
  ContractLine,
  ContractRevision,
  ContractStatus,
} from "../../../api/contracts.types";
import { listLabels } from "../../../api/customerLabels";
import type { CustomerLabel } from "../../../api/types";
import { BoundedList } from "../../../components/BoundedList";
import { ConfirmDialog } from "../../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../../components/ConfirmDialog";
import { EditModeToggle } from "../../../components/EditModeToggle";
import { useToast } from "../../../components/ToastProvider";
import { useAuth } from "../../../auth/AuthContext";
import { canManageContracts } from "../../../auth/permissions";
import { useEditMode } from "../../../lib/useEditMode";
import { contractTypeLabel } from "../../../lib/contractTypeLabel";
import { ContractFormDialog } from "./ContractFormDialog";
import { ContractInvoicePreview } from "./ContractInvoicePreview";
import {
  formatDate,
  formatMoney,
  formatNumber,
  lineValue,
} from "./contractTables";

type Tab = "general" | "projects" | "billing" | "revisions";

/** W20 — `kind` and the three line planning fields are served by the
 *  backend but `api/contracts.types.ts` belongs to another agent this
 *  round, so the shapes are narrowed here (the Sprint 183 FacturenPage
 *  precedent). Optional throughout: a server that predates them still
 *  renders. */
type ContractWithKind = Contract & { kind?: string };
type PlannedLine = ContractLine & {
  frequency_per_year?: number | null;
  norm?: string;
  department?: number | null;
  department_name?: string | null;
};

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

  const [contract, setContract] = useState<ContractWithKind | null>(null);
  const [revisions, setRevisions] = useState<ContractRevision[]>([]);
  const [tab, setTab] = useState<Tab>("general");
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [revisionOpen, setRevisionOpen] = useState(false);
  const [activating, setActivating] = useState(false);
  const toast = useToast();
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

  // W20 — an EXTRA_WORK register's lines are PROJECTED from chargeable
  // jobs by the server's sync; the planning fields are authored on
  // STANDARD contracts only, so a register shows neither the columns
  // nor the inputs.
  const isRegister = contract?.kind === "EXTRA_WORK";

  // W20 — the customer's OWN department labels, for the line editor's
  // dropdown. Loaded per customer; on any failure the list stays empty
  // and the dropdown is simply absent, which is also the deliberate
  // rendering for a customer that has no departments at all.
  const customerIdForLabels = contract?.customer;
  const [departments, setDepartments] = useState<CustomerLabel[]>([]);
  useEffect(() => {
    if (customerIdForLabels === undefined || isRegister) return;
    let cancelled = false;
    listLabels(customerIdForLabels, "department", { is_active: true })
      .then((rows) => {
        if (!cancelled) setDepartments(rows);
      })
      .catch(() => {
        if (!cancelled) setDepartments([]);
      });
    return () => {
      cancelled = true;
    };
  }, [customerIdForLabels, isRegister]);

  /**
   * W16 — draft -> active, and the page SAYS SO.
   *
   * The reference system's `activate()` answers "Contract activated"
   * whatever happened. This names the contract and what changed,
   * because "which one, and is it billing now" is the question the
   * operator has the moment they press it — a contract only starts
   * raising invoices once it is ACTIVE, so this press is the one that
   * turns the money on.
   */
  async function activate() {
    if (!contract) return;
    setActivating(true);
    try {
      await updateContract(contract.id, { lifecycle: "ACTIVE" });
      reload();
      toast.push({
        variant: "success",
        title: t("actions.activatedTitle"),
        description: t("actions.activatedBody", {
          contract: contract.contract_no,
        }),
      });
    } catch (err) {
      toast.push({
        variant: "error",
        title: t("actions.activateFailed"),
        description: getApiError(err),
      });
    } finally {
      setActivating(false);
    }
  }

  const locale = i18n.language;
  const activeRevision =
    revisions.find((revision) => revision.is_active) ?? null;
  /**
   * W11 — the revision this page is WORKING ON, which is not always the
   * one in force.
   *
   * The page used to edit only the in-force revision, and that is half
   * of why contracts have been a dead end. Author a revision for next
   * month and it is correctly open, but it is not in force, so the page
   * went on showing the old one: the write succeeded and the screen
   * looked identical. That is the whole of "Create Revision does
   * nothing" — nothing was broken, there was just nowhere for the result
   * to appear.
   *
   * So: the revision being authored is the LATEST OPEN one; if every
   * revision is closed, the page shows the one in force, read-only, and
   * "New revision" is the way to change it. One revision on screen, and
   * the header says which.
   */
  const openRevision =
    [...revisions]
      .filter((revision) => !revision.is_locked)
      .sort((a, b) =>
        a.effective_from < b.effective_from ? 1 : a.effective_from > b.effective_from ? -1 : b.id - a.id,
      )[0] ?? null;
  const shownRevision = openRevision ?? activeRevision;
  const editableRevision = openRevision;
  // Memoised because the grouping below depends on it: a fresh `[]`
  // literal on every render would re-run the grouping on every render.
  const lines = useMemo(() => shownRevision?.lines ?? [], [shownRevision]);

  const lineEdit = useEditMode<number>(
    editableRevision ? lines.map((line) => line.id) : [],
  );

  /**
   * Sprint 167 §2 — the lines, grouped by LOCATION.
   *
   * A line's `amount` is one BILLING PERIOD's money, so a group's money
   * and the footer's are both put through `lineValue`, the same rule the
   * list page uses to scale a quarterly or yearly contract down to a
   * month. Two surfaces expressing the same figure by two rules is how
   * they end up disagreeing.
   *
   * Hours are NOT scaled: an hours budget answers "how much work per
   * billing period", and multiplying it by twelve would invent a figure
   * the contract never states.
   */
  const lineGroups = useMemo(() => {
    if (!contract) return [];
    const byKey = new Map<
      string,
      {
        key: string;
        label: string;
        lines: typeof lines;
        count: number;
        hours: number;
        amount: number;
      }
    >();
    for (const line of lines) {
      const key = line.building_name ?? "__none__";
      let group = byKey.get(key);
      if (!group) {
        group = {
          key,
          label: line.building_name ?? t("projects.noBuilding"),
          lines: [],
          count: 0,
          hours: 0,
          amount: 0,
        };
        byKey.set(key, group);
      }
      group.lines.push(line);
      group.count += 1;
      group.hours += lineValue(contract, line, "hours", "monthly");
      group.amount += lineValue(contract, line, "prices", "monthly");
    }
    return [...byKey.values()];
  }, [contract, lines, t]);

  const lineTotals = useMemo(
    () => ({
      hours: lineGroups.reduce((sum, group) => sum + group.hours, 0),
      amount: lineGroups.reduce((sum, group) => sum + group.amount, 0),
    }),
    [lineGroups],
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
          {/* Sprint 167 §2 — customer, number, status, LOCATION and the
              two money figures on one line, above the tiles. */}
          <p className="page-sub" data-testid="contract-header-line">
            {contract?.customer_name ?? ""}
            {contract && (
              <>
                {" · "}
                <span className={`cell-tag ${STATUS_TAG[contract.status]}`}>
                  {t(`status.${contract.status}`)}
                </span>
                {contract.buildings.length > 0 && (
                  <>
                    {" · "}
                    {contract.buildings.map((b) => b.name).join(", ")}
                  </>
                )}
                {" · "}
                <strong data-testid="contract-header-monthly">
                  {t("header.perMonth", {
                    amount: formatMoney(contract.monthly_amount, locale),
                  })}
                </strong>
                {" · "}
                <strong data-testid="contract-header-yearly">
                  {t("header.perYear", {
                    amount: formatMoney(contract.yearly_amount, locale),
                  })}
                </strong>
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
          {/* W16 — ACTIVATE IS A BUTTON, because it is a verb.
              The reference system has `POST /contracts/{id}/activate`
              and one press; ours had only a `lifecycle` dropdown three
              clicks inside the edit dialog, which is a state picker
              pretending to be an action. It reuses the ordinary PATCH
              rather than adding a second write path — the endpoint
              already validates, scopes and audits, and a dedicated
              verb would be a second door onto one change.
              Shown only on a DRAFT: a role — or a state — that cannot
              use it does not see it. */}
          {canManage && contract && contract.lifecycle === "DRAFT" && (
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={() => void activate()}
              disabled={activating}
              data-testid="contract-activate"
            >
              {activating ? t("actions.activating") : t("actions.activate")}
            </button>
          )}
          {canManage && contract && (
            <button
              type="button"
              className={
                contract.lifecycle === "DRAFT"
                  ? "btn btn-secondary btn-sm"
                  : "btn btn-primary btn-sm"
              }
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
        <section className="card card-detail-pad" data-testid="contract-general">
          {lines.length === 0 && (
            <p className="alert-info" data-testid="contract-general-no-lines">
              {t("general.noLines")}{" "}
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setTab("projects")}
                data-testid="contract-general-go-projects"
              >
                {t("billing.goProjects")}
              </button>
            </p>
          )}
          <div className="section-head" style={{ marginBottom: 8 }}>
            <div>
              <div className="section-head-title">{t("general.title")}</div>
              <div className="section-head-sub">{t("general.desc")}</div>
            </div>
          </div>
          <dl className="detail-field-grid">
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
              value={
                contract.contract_type_name
                  ? contractTypeLabel(
                      contract.contract_type_name,
                      contract.contract_type_standard_slot,
                      t,
                    )
                  : "—"
              }
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
        <section className="card card-detail-pad" data-testid="contract-projects">
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

          {/* W11 — which revision these projects belong to, always.
              Without it, a page that sometimes shows the agreement in
              force and sometimes the one being drafted is a page whose
              numbers a reader cannot place. */}
          {shownRevision && (
            <p className="muted" data-testid="contract-lines-scope">
              {shownRevision.is_locked
                ? t("projects.lockedNotice", { label: shownRevision.label })
                : t("projects.draftNotice", {
                    label: shownRevision.label,
                    date: shownRevision.effective_from,
                  })}
            </p>
          )}

          <div className="table-wrap">
            <table className="data-table data-table-dense">
              <thead>
                <tr>
                  <th>{t("projects.name")}</th>
                  <th>{t("projects.building")}</th>
                  {/* W20 — the planning trio, absent on a register:
                      register lines are projected, not authored. */}
                  {!isRegister && (
                    <>
                      <th>{t("projects.department")}</th>
                      <th className="contract-num">
                        {t("projects.frequencyPerYear")}
                      </th>
                      <th>{t("projects.norm")}</th>
                    </>
                  )}
                  <th className="contract-num">{t("projects.hours")}</th>
                  <th className="contract-num">{t("projects.area")}</th>
                  <th className="contract-num">{t("projects.amount")}</th>
                  <th className="contract-num">{t("projects.vat")}</th>
                  {lineEdit.editMode && <th />}
                </tr>
              </thead>
              <tbody>
                {lineGroups.map((group) => (
                  <Fragment key={group.key}>
                    {/* One row per LOCATION, carrying that location's own
                        count, hours and money — the reference groups the
                        projects this way because a contract is read
                        building by building. */}
                    <tr
                      className="contract-group-row"
                      data-testid={`contract-line-group-${group.key}`}
                    >
                      {/* The label spans the planning columns too, so
                          the group's hours stay under the hours
                          column. */}
                      <td colSpan={isRegister ? 2 : 5}>
                        <strong>{group.label}</strong>
                        <span className="muted small" style={{ marginLeft: 8 }}>
                          {t("projects.groupCount", { count: group.count })}
                        </span>
                      </td>
                      <td className="contract-num">
                        <strong>{formatNumber(String(group.hours), locale)}</strong>
                      </td>
                      <td className="contract-num" />
                      <td className="contract-num">
                        <strong>{formatMoney(String(group.amount), locale)}</strong>
                      </td>
                      <td className="contract-num" />
                      {lineEdit.editMode && <td />}
                    </tr>
                    {group.lines.map((line) => (
                  <tr key={line.id}>
                    <td>{line.name}</td>
                    <td>{line.building_name ?? "—"}</td>
                    {!isRegister && (
                      <>
                        <td>{(line as PlannedLine).department_name ?? "—"}</td>
                        <td className="contract-num">
                          {(line as PlannedLine).frequency_per_year ?? "—"}
                        </td>
                        <td>{(line as PlannedLine).norm || "—"}</td>
                      </>
                    )}
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
                  </Fragment>
                ))}
                {lines.length === 0 && (
                  <tr data-testid="contract-projects-empty">
                    <td colSpan={isRegister ? 7 : 10} className="muted">
                      {/* Sprint 172 §2 — a contract with no lines shows
                          zeros everywhere, and nothing said WHY. Every
                          figure on this contract is computed from these
                          rows, so the empty state says so and the add
                          control sits directly under it. */}
                      <strong>{t("projects.emptyTitle")}</strong>
                      <br />
                      {t("projects.emptyWhy")}
                    </td>
                  </tr>
                )}
                {lines.length > 0 && (
                  <tr
                    className="contract-grand-total"
                    data-testid="contract-lines-total"
                  >
                    <td colSpan={isRegister ? 2 : 5}>
                      <strong>{t("projects.totalPerMonth")}</strong>
                    </td>
                    <td className="contract-num">
                      <strong>{formatNumber(String(lineTotals.hours), locale)}</strong>
                    </td>
                    <td className="contract-num" />
                    <td className="contract-num">
                      <strong>{formatMoney(String(lineTotals.amount), locale)}</strong>
                    </td>
                    <td className="contract-num" />
                    {lineEdit.editMode && <td />}
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {canManage && editableRevision && (
            <AddLineForm
              revisionId={editableRevision.id}
              buildings={contract?.buildings ?? []}
              departments={isRegister ? [] : departments}
              showPlanning={!isRegister}
              onAdded={reload}
              onError={(message) => setError(message)}
            />
          )}
        </section>
      )}

      {tab === "billing" && contract && (
        <section className="card card-detail-pad" data-testid="contract-billing">
          <div className="section-head" style={{ marginBottom: 8 }}>
            <div>
              <div className="section-head-title">{t("billing.title")}</div>
              <div className="section-head-sub">{t("billing.desc")}</div>
            </div>
          </div>
          {lines.length === 0 && (
            <p className="alert-info" data-testid="contract-billing-no-lines">
              {t("billing.noLines")}{" "}
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setTab("projects")}
                data-testid="contract-billing-go-projects"
              >
                {t("billing.goProjects")}
              </button>
            </p>
          )}
          <dl className="detail-field-grid">
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
        <section className="card card-detail-pad" data-testid="contract-revisions">
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
                /* Sprint 177 §9 — the figure is the amount the revision in
                   force TODAY bills per month. It is neither a
                   month-to-date total nor a forecast, and nothing on the
                   screen said so. */
                hint={t("revisions.currentMonthlyAsOf", {
                  date: formatDate(new Date().toISOString(), locale),
                })}
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

function Tile({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  /** Sprint 177 §9 — what the figure MEASURES, when the label alone
   *  cannot say it. "Current monthly" is a correct number that a reader
   *  cannot interpret: today, this month so far, or a whole month? The
   *  hint answers that without lengthening the label. */
  hint?: string;
}) {
  return (
    <div className="summary-stat">
      <span className="summary-stat-label">{label}</span>
      <span className="summary-stat-value">{value}</span>
      {hint && <span className="muted small">{hint}</span>}
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
      <dt className="detail-field-label">{label}</dt>
      <dd className="detail-field-value">{value}</dd>
    </div>
  );
}

function AddLineForm({
  revisionId,
  buildings,
  departments,
  showPlanning,
  onAdded,
  onError,
}: {
  revisionId: number;
  buildings: { id: number; name: string }[];
  /** W20 — the contract's customer's OWN department labels. An empty
   *  list renders NO dropdown at all (absent, not empty): a customer
   *  without departments does not get an inapplicable control. */
  departments: CustomerLabel[];
  /** False on an EXTRA_WORK register, whose lines are projected. */
  showPlanning: boolean;
  onAdded: () => void;
  onError: (message: string) => void;
}) {
  const { t } = useTranslation("contracts");
  const [name, setName] = useState("");
  const [hours, setHours] = useState("0.00");
  const [amount, setAmount] = useState("0.00");
  const [area, setArea] = useState("");
  const [building, setBuilding] = useState<number | "">("");
  const [frequency, setFrequency] = useState("");
  const [norm, setNorm] = useState("");
  const [department, setDepartment] = useState<number | "">("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!name.trim()) return;
    setBusy(true);
    try {
      // W20 — the three planning fields. `frequency_per_year` is a
      // COUNT per year (the later 52-week grid buckets on it), never
      // money. The payload type lives in `api/contracts.types.ts`,
      // another agent's file this round — hence the local widening.
      const payload: Parameters<typeof createContractLine>[1] & {
        frequency_per_year?: number | null;
        norm?: string;
        department?: number | null;
      } = {
        name: name.trim(),
        hours,
        amount,
        area_m2: area || null,
        building: building === "" ? null : building,
      };
      if (showPlanning) {
        payload.frequency_per_year =
          frequency === "" ? null : Number(frequency);
        payload.norm = norm.trim();
        payload.department = department === "" ? null : department;
      }
      await createContractLine(revisionId, payload);
      setName("");
      setHours("0.00");
      setAmount("0.00");
      setArea("");
      setBuilding("");
      setFrequency("");
      setNorm("");
      setDepartment("");
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
      {showPlanning && (
        <>
          {departments.length > 0 && (
            <select
              className="field-input"
              aria-label={t("projects.department")}
              value={department}
              onChange={(event) =>
                setDepartment(
                  event.target.value === ""
                    ? ""
                    : Number(event.target.value),
                )
              }
              data-testid="contract-line-department"
            >
              <option value="">{t("projects.noDepartment")}</option>
              {departments.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.name}
                </option>
              ))}
            </select>
          )}
          <input
            className="field-input"
            type="number"
            min="0"
            step="1"
            aria-label={t("projects.frequencyPerYear")}
            placeholder={t("projects.frequencyPerYear")}
            value={frequency}
            onChange={(event) => setFrequency(event.target.value)}
            data-testid="contract-line-frequency"
          />
          <input
            className="field-input"
            aria-label={t("projects.norm")}
            placeholder={t("projects.norm")}
            value={norm}
            onChange={(event) => setNorm(event.target.value)}
            data-testid="contract-line-norm"
          />
        </>
      )}
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
