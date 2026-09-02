import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ClipboardList, Plus } from "lucide-react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../../api/client";
import {
  createContractLine,
  createContractRevision,
  deleteContractLine,
  getContract,
  getContractForecast,
  listContractRevisions,
  updateContract,
} from "../../../api/contracts";
import type {
  Contract,
  ContractForecast,
  ContractLine,
  ContractRevision,
} from "../../../api/contracts.types";
import { ContractTermDialog, Term } from "../../../components/contracts/ContractTerms";
import { contractSentence } from "../../../components/contracts/contractSentence";
import { RoadTabs } from "../../../components/guide/RoadTabs";
import { StartHere } from "../../../components/guide/StartHere";
import { DoneBanner } from "../../../components/guide/DoneBanner";
import { useDoneBanner } from "../../../components/guide/useDoneBanner";
import { ConnectionLine } from "../../../components/guide/ConnectionLine";
import { HIGHLIGHT_CLASS, HIGHLIGHT_MS } from "../../../components/guide/highlight";
import {
  CONTRACT_ROAD,
  DEFAULT_ENDING_HORIZON_DAYS,
  contractRoadKeyOf,
} from "../../../lib/contractRoad";
import type { ContractTerm } from "../../../components/contracts/ContractTerms";
import { listLabels } from "../../../api/customerLabels";
import type { CustomerLabel } from "../../../api/types";
import { BoundedList } from "../../../components/BoundedList";
import { ContractPlanningGrid } from "../../../components/contracts/ContractPlanningGrid";
import { ConfirmDialog } from "../../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../../components/ConfirmDialog";
import { EditModeToggle } from "../../../components/EditModeToggle";
import { EmptyState } from "../../../components/EmptyState";
import { PageHeader } from "../../../components/PageHeader";
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
import { CONTRACT_STATUS_TAG } from "../../../lib/contractStatusTag";

type Tab = "general" | "projects" | "planning" | "billing" | "revisions";

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

// W23 — "planning" sits between the projects it plans and the billing
// they earn. A register (kind=EXTRA_WORK) mirrors chargeable jobs and
// has no standing lines to plan, so the tab is ABSENT there (filtered
// at render), not empty.
const TABS: Tab[] = ["general", "projects", "planning", "billing", "revisions"];

// Contract statuses reuse the table's existing `cell-tag` vocabulary
// rather than a badge palette of their own. Same mapping as
// `ContractsAdminPage`; both read from the design system, so the two
// screens cannot show the same contract in different colours.

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
const todayIso = new Date().toISOString().slice(0, 10);

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
  // P-3 §C.2 — which term is being taught, and the forecast the
  // teaching examples draw their dates and amounts from.
  const [term, setTerm] = useState<ContractTerm | null>(null);
  const [forecast, setForecast] = useState<ContractForecast | null>(null);
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

  // P-12 C4 (§D.24 rule 4) — the after-action banner and the added
  // line's ten-second tint.
  const contractDone = useDoneBanner(`contract-${contractId}`);
  const [addedLineId, setAddedLineId] = useState<number | null>(null);
  useEffect(() => {
    if (addedLineId === null) return;
    const timer = window.setTimeout(() => setAddedLineId(null), HIGHLIGHT_MS);
    return () => window.clearTimeout(timer);
  }, [addedLineId]);

  useEffect(() => {
    if (!Number.isFinite(id)) return;
    let cancelled = false;
    getContractForecast(id, new Date().getFullYear())
      .then((data) => {
        if (!cancelled) setForecast(data);
      })
      .catch(() => {
        // The examples simply have fewer numbers to show.
        if (!cancelled) setForecast(null);
      });
    return () => {
      cancelled = true;
    };
  }, [id, requestKey]);

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
      // P-12 C4 — a banner, not a toast: what happened, what it means
      // for the money, and where the result will appear (§D.24 rule 4).
      contractDone.announce({
        title: t("road.activated_title", { no: contract.contract_no }),
        body: t("road.activated_body"),
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
  // P-12 C2 — the road step, from the same facts the server's
  // status_filter_q reads (the 60-day horizon is the server's
  // ENDING_SOON_DAYS; /contracts/stats/ serves it as ending_soon_days).
  const roadKey = contract
    ? contractRoadKeyOf(contract, DEFAULT_ENDING_HORIZON_DAYS)
    : null;
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

  /* P-11 C — "has lines" reads BOTH counts: the shown revision's lines
     (what the tabs render) and the served `line_count` (the revision in
     force). A freshly drafted empty revision on a running contract must
     not blank the tiles the active revision still earns; only a contract
     with no lines ANYWHERE shows the one teaching card instead. */
  const hasLines = (contract?.line_count ?? 0) > 0 || lines.length > 0;

  /* P-13 F (E2) — the detail's Start here names the ONE missing thing,
     the list's P-12 C1 precedence brought onto the contract itself:
     no lines beats an unactivated draft beats a nearing end. Ended and
     cancelled contracts are read-only history — nothing is missing
     there, so nothing renders; likewise an active contract with lines
     and a far-off (or no) end. A reader who cannot use a door does not
     get the button (W16), but the sentence still tells the truth. */
  const startHere = (() => {
    if (!contract || !roadKey || roadKey === "ended") return null;
    if (!hasLines) {
      return {
        sentence: t("detail.start_no_lines"),
        action: {
          label: t("detail.addFirstLine"),
          onClick: () => setTab("projects"),
        },
      };
    }
    if (roadKey === "draft") {
      return {
        sentence: t("detail.start_draft"),
        action: canManage
          ? {
              label: activating ? t("actions.activating") : t("actions.activate"),
              onClick: () => {
                if (!activating) void activate();
              },
            }
          : undefined,
      };
    }
    if (roadKey === "ending") {
      return {
        sentence: t("detail.start_ending", {
          date: contract.end_date ? formatDate(contract.end_date, locale) : "",
        }),
        action: canManage
          ? {
              label: t("detail.start_ending_action"),
              onClick: () => setEditOpen(true),
            }
          : undefined,
      };
    }
    return null;
  })();

  /* P-11 C — the ONE card a line-less contract shows on the General and
     Billing tabs, replacing the two old alert-info notices: what a line
     IS (the owner's sentence), and the one door to adding the first one
     (the Lines tab, where the add form lives). */
  const emptyLinesCard = (
    <EmptyState
      icon={ClipboardList}
      title={t("detail.noLinesTitle")}
      description={t("detail.noLinesDesc")}
      testId="contracts-empty-lines-card"
      action={
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => setTab("projects")}
          data-testid="contract-add-first-line"
        >
          {t("detail.addFirstLine")}
        </button>
      }
    />
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

  const unavailableCard = (
    /* P-6 V3 — NEVER A VOID. A contract that could not be read says so
       in words, with the way back. */
    <section className="card" role="status" data-testid="contract-unavailable" style={{ padding: 22 }}>
      <div className="section-head-title">{t("detail.unavailableTitle")}</div>
      <p className="muted" style={{ marginTop: 6 }}>
        {error || t("detail.unavailableBody")}
      </p>
      <Link to="/admin/contracts" className="btn btn-secondary btn-sm" style={{ marginTop: 10 }}>
        {t("actions.backToList")}
      </Link>
    </section>
  );

  if (!Number.isFinite(id)) {
    return (
      <div>
        <PageHeader
          backLink={{ to: "/admin/contracts", label: t("actions.backToList") }}
          eyebrow={t("list.title")}
          title={t("errors.notFound")}
        />
        {unavailableCard}
      </div>
    );
  }

  /* P-6 V3 (§D.6 rule 3) — ONE primary per state: Activate while the
     contract is a DRAFT (the press that turns the money on), Edit
     otherwise. Refresh is gone; every mutation already re-fetches.

     W16 — ACTIVATE IS A BUTTON, because it is a verb. The reference
     system has `POST /contracts/{id}/activate` and one press; ours had
     only a `lifecycle` dropdown three clicks inside the edit dialog,
     which is a state picker pretending to be an action. It reuses the
     ordinary PATCH rather than adding a second write path — the endpoint
     already validates, scopes and audits. Shown only on a DRAFT: a role
     — or a state — that cannot use it does not see it. */
  const headerActions =
    canManage && contract ? (
      <>
        {contract.lifecycle === "DRAFT" && (
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={() => void activate()}
            disabled={activating}
            title={activating ? t("actions.activating") : undefined}
            data-testid="contract-activate"
          >
            {activating ? t("actions.activating") : t("actions.activate")}
          </button>
        )}
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
      </>
    ) : null;

  return (
    <div>
      <PageHeader
        backLink={{ to: "/admin/contracts", label: t("actions.backToList") }}
        eyebrow={t("list.title")}
        title={
          contract
            ? contract.contract_no
            : loading
              ? t("list.loading")
              : t("detail.unavailableTitle")
        }
        /* P-3 §C.1 — the status word teaches on click. */
        statusPill={
          contract ? (
            <Term term="status" onOpen={setTerm} testId="contract-term-status-head">
              <span className={`cell-tag ${CONTRACT_STATUS_TAG[contract.status]}`}>
                {t(`status.${contract.status}`)}
              </span>
            </Term>
          ) : undefined
        }
        /* Sprint 167 §2 / P-3 §C.1 — the contract reads as ONE sentence:
           "B Amsterdam — € 850 per maand voor B1 + B2 — sinds jan 2026 —
           volgende periode: sep". */
        subtitle={
          contract ? (
            <span data-testid="contract-header-line">
              {contractSentence(contract, t, locale)}
            </span>
          ) : undefined
        }
        actions={headerActions}
      />

      {/* P-12 C2 (§D.24 rule 3) — where this contract stands on its
          road, and what the current step means. A cancelled contract
          is off the road and shows none. */}
      {contract && roadKey && (
        <>
          <RoadTabs
            variant="progress"
            steps={CONTRACT_ROAD.map((key) => ({
              key,
              step: t(`road.${key}_step`),
              label: t(`road.${key}_label`),
            }))}
            activeKey={roadKey}
            ariaLabel={t("road.aria")}
            testIdPrefix="contract-road"
          />
          <p
            className="muted small"
            style={{ margin: "0 0 14px" }}
            data-testid="contract-road-teach"
          >
            {t(`road.step_teach_${roadKey}`)}
          </p>
        </>
      )}

      {/* P-13 F (E2) — between the road's teach line and the banner:
          the one missing thing on THIS contract, with its one door. */}
      {startHere && (
        <StartHere testId="contract-start-here" action={startHere.action}>
          {startHere.sentence}
        </StartHere>
      )}

      {contractDone.done && (
        <DoneBanner
          done={contractDone.done}
          onDismiss={contractDone.dismiss}
          testId="contract-done"
        />
      )}

      {error && (
        <div className="alert-error" role="alert">
          {error}
        </div>
      )}

      {loading && !contract ? (
        <div className="loading-bar">
          <div className="loading-bar-fill" />
        </div>
      ) : !contract ? (
        unavailableCard
      ) : (
        <>
      {/* P-6 V3 (§D.6 rule 5) — FACTS FIRST: who, where, when, what
          state. Presentation only; every value is the server's. */}
      <div className="facts" data-testid="contract-facts">
        <div className="ew-ctx-block" data-testid="contract-fact-customer">
          <div className="ew-ctx-label">{t("fields.customer")}</div>
          <div className="ew-ctx-body">
            <div className="ew-ctx-strong">
              <Link to={`/admin/customers/${contract.customer}`}>
                {contract.customer_name ?? ""}
              </Link>
            </div>
            {contract.contract_type_name && (
              <div className="ew-ctx-sub">
                {contractTypeLabel(
                  contract.contract_type_name,
                  contract.contract_type_standard_slot,
                  t,
                )}
              </div>
            )}
          </div>
        </div>
        <div className="ew-ctx-block" data-testid="contract-fact-locations">
          <div className="ew-ctx-label">{t("fields.locations")}</div>
          <div className="ew-ctx-body">
            <div className="ew-ctx-strong">
              {contract.buildings.length === 0
                ? t("sentence.no_locations")
                : t("facts.locations", { count: contract.buildings.length })}
            </div>
            {contract.buildings.length > 0 && (
              <div className="ew-ctx-sub">
                {contract.buildings
                  .slice(0, 2)
                  .map((building) => building.name)
                  .join(", ")}
              </div>
            )}
          </div>
        </div>
        <div className="ew-ctx-block" data-testid="contract-fact-period">
          <div className="ew-ctx-label">{t("facts.period")}</div>
          <div className="ew-ctx-body">
            <div className="ew-ctx-strong">{formatDate(contract.start_date, locale)}</div>
            <div className="ew-ctx-sub">
              {contract.end_date
                ? t("facts.until", { date: formatDate(contract.end_date, locale) })
                : t("fields.openEnded")}
            </div>
          </div>
        </div>
        <div className="ew-ctx-block" data-testid="contract-fact-status">
          <div className="ew-ctx-label">{t("fields.status")}</div>
          <div className="ew-ctx-body">
            <div className="ew-ctx-strong">{t(`status.${contract.status}`)}</div>
            {activeRevision && (
              <div className="ew-ctx-sub">{activeRevision.label}</div>
            )}
          </div>
        </div>
      </div>

      {/* Header tiles — all four DERIVED from the active revision.
          P-11 C — with no lines anywhere they would be four zeros
          dressed as facts, so at zero lines they do not render at all
          (their Terms go with them, the §D.21 C7 rule) and the one
          card on the tabs below says why instead. */}
      {hasLines && (
        <div className="summary-grid" data-testid="contract-tiles">
          <Tile
            label={<Term term="monthly" onOpen={setTerm}>{t("tiles.monthly")}</Term>}
            value={formatMoney(contract.monthly_amount, locale)}
          />
          <Tile
            label={<Term term="yearly" onOpen={setTerm}>{t("tiles.yearly")}</Term>}
            value={formatMoney(contract.yearly_amount, locale)}
          />
          <Tile
            label={<Term term="hours" onOpen={setTerm}>{t("tiles.hours")}</Term>}
            value={formatNumber(contract.total_hours, locale)}
          />
          <Tile
            label={<Term term="projects" onOpen={setTerm}>{t("tiles.lineCount")}</Term>}
            value={String(contract.line_count)}
          />
        </div>
      )}

      <div className="status-tabs" role="tablist" data-testid="contract-tabs">
        {(isRegister ? TABS.filter((key) => key !== "planning") : TABS).map((key) => (
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
          {/* P-11 C — the old alert-info notice is replaced by the one
              teaching card (same card as on the Billing tab). */}
          {!hasLines && emptyLinesCard}
          <div className="section-head" style={{ marginBottom: 8 }}>
            <div>
              <div className="section-head-title">{t("general.title")}</div>
              <div className="section-head-sub">{t("general.desc")}</div>
            </div>
          </div>
          <dl className="detail-field-grid">
            <Field
              label={<Term term="contractNo" onOpen={setTerm}>{t("fields.contractNo")}</Term>}
              value={contract.contract_no}
            />
            <Field
              label={<Term term="customer" onOpen={setTerm}>{t("fields.customer")}</Term>}
              value={
                <Link to={`/admin/customers/${contract.customer}`}>
                  {contract.customer_name ?? ""}
                </Link>
              }
            />
            <Field
              label={<Term term="locations" onOpen={setTerm}>{t("fields.locations")}</Term>}
              value={
                contract.buildings.length === 0 ? (
                  t("sentence.no_locations")
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
                        <li key={building.id} data-testid="contract-location-row">
                          <Link to={`/admin/buildings/${building.id}`}>
                            {building.name}
                          </Link>
                          {/* P-5 S7 — the connected fact: how this
                              building's bills are divided, linking to
                              the split itself. */}
                          <span className="muted small contract-connected-line">
                            {building.cost_shares && building.cost_shares.length > 0 ? (
                              <>
                                {t("connections.billed_split", {
                                  shares: building.cost_shares
                                    .map((s) => `${s.customer_name} ${Number(s.share_pct)}%`)
                                    .join(" / "),
                                })}{" "}
                                <Link
                                  to={`/admin/buildings/${building.id}?piece=cost-share`}
                                  data-testid="contract-location-split-link"
                                >
                                  {t("connections.open_split")}
                                </Link>
                              </>
                            ) : (
                              t("connections.billed_whole", {
                                customer: contract.customer_name ?? "",
                              })
                            )}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </BoundedList>
                )
              }
            />
            {/* P-3 §C.3 — an unset fact is absent, never a dash. */}
            {contract.contract_type_name && (
              <Field
                label={<Term term="type" onOpen={setTerm}>{t("fields.type")}</Term>}
                value={contractTypeLabel(
                  contract.contract_type_name,
                  contract.contract_type_standard_slot,
                  t,
                )}
              />
            )}
            <Field
              label={<Term term="status" onOpen={setTerm}>{t("fields.status")}</Term>}
              value={t(`status.${contract.status}`)}
            />
            <Field
              label={<Term term="startDate" onOpen={setTerm}>{t("fields.startDate")}</Term>}
              value={formatDate(contract.start_date, locale)}
            />
            <Field
              label={<Term term="endDate" onOpen={setTerm}>{t("fields.endDate")}</Term>}
              value={
                contract.end_date
                  ? formatDate(contract.end_date, locale)
                  : t("fields.openEnded")
              }
            />
            <Field
              label={<Term term="hoursPerYear" onOpen={setTerm}>{t("fields.hoursPerYear")}</Term>}
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
            {contract.description && (
              <Field label={t("fields.description")} value={contract.description} />
            )}
            {contract.notes && <Field label={t("fields.notes")} value={contract.notes} />}
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

          {/* Sprint 172 §2 / P-6 V3 — a contract with no lines shows
              zeros everywhere; the empty state says why, ONCE, and the
              add control sits directly under it. No table renders for
              nothing (rule 13). */}
          {lines.length === 0 ? (
            <EmptyState
              icon={ClipboardList}
              title={t("projects.emptyTitle")}
              description={t("projects.emptyWhy")}
              compact
              testId="contract-projects-empty"
            />
          ) : (
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
                  <tr
                    key={line.id}
                    className={
                      addedLineId === line.id ? HIGHLIGHT_CLASS : undefined
                    }
                  >
                    <td>
                      {line.name}
                      {/* P-12 C3 (§D.24 rule 6) — which recurring work
                          runs this line, in words with the one link. */}
                      {(line.recurring ?? []).map((job) => (
                        <ConnectionLine
                          key={job.id}
                          to={`/planned-work/${job.id}`}
                          linkLabel={job.title}
                          testId={`contract-line-recurring-${line.id}`}
                        >
                          {t(
                            job.is_active
                              ? "road.line_runs_as"
                              : "road.line_ran_as",
                          )}
                        </ConnectionLine>
                      ))}
                    </td>
                    <td>{line.building_name ?? t("projects.wholeContract")}</td>
                    {!isRegister && (
                      <>
                        <td>
                          {(line as PlannedLine).department_name ?? t("projects.noDepartment")}
                        </td>
                        <td className="contract-num">
                          {(line as PlannedLine).frequency_per_year ?? ""}
                        </td>
                        <td>{(line as PlannedLine).norm || ""}</td>
                      </>
                    )}
                    <td className="contract-num">{formatNumber(line.hours, locale)}</td>
                    <td className="contract-num">
                      {line.area_m2 ? formatNumber(line.area_m2, locale) : ""}
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
              </tbody>
            </table>
          </div>
          )}

          {canManage && editableRevision && (
            <AddLineForm
              revisionId={editableRevision.id}
              buildings={contract?.buildings ?? []}
              departments={isRegister ? [] : departments}
              showPlanning={!isRegister}
              onAdded={(created) => {
                reload();
                // P-12 C4 — say what happened and the one next step;
                // tint the new line when the reload brings it in.
                setAddedLineId(created.id);
                contractDone.announce({
                  title: t("road.line_added_title", {
                    name: created.name,
                    amount: formatMoney(created.amount, locale),
                  }),
                  body: t(
                    contract?.lifecycle === "DRAFT"
                      ? "road.line_added_next_draft"
                      : "road.line_added_next_active",
                  ),
                });
              }}
              onError={(message) => setError(message)}
            />
          )}
        </section>
      )}

      {/* W23 — the year×week planning grid. Absent (not empty) on a
          register: the tab itself is filtered out above. A name and
          the grid; editing lives on the recurring job's calendar. */}
      {tab === "general" && contract && (contract.visits || contract.invoice_trail) && (
        <section className="card card-detail-pad" data-testid="contract-connections">
          <header className="section-head">
            <span className="section-head-title">{t("connections.title")}</span>
          </header>
          <p className="muted small" data-testid="contract-connections-intro">
            {t("connections.intro")}
          </p>
          <div className="contract-connections-grid">
            <div data-testid="contract-visits">
              <div className="field-label">{t("connections.visits_title")}</div>
              {contract.visits && contract.visits.total > 0 ? (
                <ul className="contract-plain-list">
                  {[...contract.visits.recent, ...contract.visits.next].map((visit) => (
                    <li key={visit.id} data-testid="contract-visit-row">
                      {visit.ticket_id ? (
                        <Link to={`/tickets/${visit.ticket_id}`}>
                          {visit.ticket_no ?? visit.recurring_job_title}
                        </Link>
                      ) : (
                        <Link to={`/planned-work/${visit.recurring_job_id}`}>
                          {visit.recurring_job_title}
                        </Link>
                      )}
                      <span className="muted small contract-connected-line">
                        {t(
                          visit.planned_date > todayIso
                            ? "connections.visit_next"
                            : "connections.visit_recent",
                          {
                            date: formatDate(`${visit.planned_date}T00:00:00`, locale),
                            job: visit.recurring_job_title,
                          },
                        )}
                      </span>
                    </li>
                  ))}
                  {contract.visits.total >
                    contract.visits.recent.length + contract.visits.next.length && (
                    <li className="muted small">
                      {t("connections.visits_more", {
                        count:
                          contract.visits.total -
                          contract.visits.recent.length -
                          contract.visits.next.length,
                      })}
                    </li>
                  )}
                </ul>
              ) : (
                <p className="muted small" data-testid="contract-visits-empty">
                  {t("connections.visits_empty")}
                </p>
              )}
            </div>
            <div data-testid="contract-invoice-trail">
              <div className="field-label">{t("connections.invoices_title")}</div>
              {contract.invoice_trail && contract.invoice_trail.length > 0 ? (
                <ul className="contract-plain-list">
                  {contract.invoice_trail.map((row) => (
                    <li key={row.invoice_id} data-testid="contract-invoice-row">
                      <Link to={`/invoices/${row.invoice_id}`}>
                        {row.number ?? t("connections.invoice_concept")}
                      </Link>
                      <span className="muted small contract-connected-line">
                        {t("connections.invoice_line", {
                          from: formatDate(`${row.period_start}T00:00:00`, locale),
                          to: formatDate(`${row.period_end}T00:00:00`, locale),
                          amount: formatMoney(row.total_amount, locale),
                        })}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="muted small" data-testid="contract-invoice-trail-empty">
                  {t("connections.invoices_empty")}
                </p>
              )}
            </div>
          </div>
        </section>
      )}
      {tab === "planning" && contract && !isRegister && (
        <section className="card card-detail-pad" data-testid="contract-planning">
          <header className="section-head">
            <span className="section-head-title">{t("planning.title")}</span>
          </header>
          <ContractPlanningGrid contractId={contract.id} />
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
          {/* P-11 C — the old alert-info notice is replaced by the one
              teaching card (same card as on the General tab). */}
          {!hasLines && emptyLinesCard}
          <dl className="detail-field-grid">
            <Field
              label={<Term term="billingPeriod" onOpen={setTerm}>{t("fields.billingPeriod")}</Term>}
              value={t(`billingPeriod.${contract.billing_period}`)}
            />
            <Field
              label={<Term term="billingDay" onOpen={setTerm}>{t("fields.billingDay")}</Term>}
              value={String(contract.billing_day)}
            />
            <Field
              label={<Term term="billingType" onOpen={setTerm}>{t("fields.billingType")}</Term>}
              value={t(`billingType.${contract.billing_type}`)}
            />
            <Field
              label={<Term term="paymentTerms" onOpen={setTerm}>{t("fields.paymentTerms")}</Term>}
              value={t("fields.days", { count: contract.payment_terms_days })}
            />
            <Field
              label={<Term term="proration" onOpen={setTerm}>{t("fields.proration")}</Term>}
              value={
                contract.start_proration ? t("fields.on") : t("fields.off")
              }
            />
          </dl>
          {/* P-11 C — no preview of invoices that would all be € 0.00:
              with zero lines the card above already says what is
              missing; the preview returns the moment a line exists. */}
          {hasLines && (
            <ContractInvoicePreview contractId={contract.id} onTerm={setTerm} />
          )}
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
                label={<Term term="revision" onOpen={setTerm}>{t("revisions.activeRevision")}</Term>}
                value={activeRevision.label}
              />
              <Tile
                label={<Term term="revisionState" onOpen={setTerm}>{t("revisions.effectiveSince")}</Term>}
                value={formatDate(activeRevision.effective_from, locale)}
              />
              {/* P-6 V3 (rule 13) — the monthly amount is the header's
                  first tile; it is not said a second time here. */}
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
                    <th><Term term="revision" onOpen={setTerm}>{t("revisions.label")}</Term></th>
                    <th>{t("revisions.effectiveFrom")}</th>
                    <th className="contract-num">{t("revisions.amount")}</th>
                    <th className="contract-num">
                      <Term term="projects" onOpen={setTerm}>{t("revisions.lines")}</Term>
                    </th>
                    <th>{t("revisions.author")}</th>
                    <th><Term term="revisionState" onOpen={setTerm}>{t("revisions.state")}</Term></th>
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
                      <td>{revision.created_by_name ?? ""}</td>
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

        </>
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

      {/* P-3 §C.2 — every term teaches on click, with THIS contract's
          own numbers. Rendered unconditionally, driven through its ref. */}
      <ContractTermDialog
        term={term}
        context={{ contract, revisions, forecast }}
        onClose={() => setTerm(null)}
      />
    </div>
  );
}

function Tile({
  label,
  value,
}: {
  label: React.ReactNode;
  value: string;
}) {
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
  label: React.ReactNode;
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
  onAdded: (created: ContractLine) => void;
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
      const created = await createContractLine(revisionId, payload);
      setName("");
      setHours("0.00");
      setAmount("0.00");
      setArea("");
      setBuilding("");
      setFrequency("");
      setNorm("");
      setDepartment("");
      onAdded(created);
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
        title={
          busy
            ? t("actions.saving")
            : !name.trim()
              ? t("projects.addNeedsName")
              : undefined
        }
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
        <h2 className="section-head-title" style={{ margin: 0 }}>
          {t("revisions.create")}
        </h2>
        <p className="muted" style={{ marginTop: 6 }}>{t("revisions.createHint")}</p>

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
            title={busy ? t("actions.saving") : undefined}
            data-testid="contract-revision-save"
          >
            {busy ? t("actions.saving") : t("actions.save")}
          </button>
        </div>
      </div>
    </div>
  );
}
