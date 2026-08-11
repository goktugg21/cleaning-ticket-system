import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  Mail,
  MapPin,
  Receipt,
  ShieldCheck,
  Tag,
  Ticket,
  UserCog,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../../api/client";
import {
  getCompany,
  getCustomer,
  getCustomerSummary,
  listCustomerBuildings,
  reactivateCustomer,
} from "../../../api/admin";
import type {
  CompanyAdmin,
  CustomerAdmin,
  CustomerBuildingMembership,
  CustomerSummary,
} from "../../../api/types";
import { useAuth } from "../../../auth/AuthContext";
import { BoundedList } from "../../../components/BoundedList";
import {
  LinkedBuildingCounts,
  LinkedBuildingIdentity,
} from "../../../components/LinkedBuildingCell";
import { ConfirmDialog } from "../../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../../components/ConfirmDialog";

import { CustomerSubPageHeader } from "./CustomerSubPageHeader";

/**
 * Customer Overview page (admin variant).
 *
 * Sprint 153 §4 rebuilt the order. The owner's complaint was that the
 * page opened with an explainer paragraph and an address card, and said
 * nothing operational. Top-to-bottom now:
 *
 *   1. CustomerSubPageHeader (back link + name + Edit basics action).
 *   2. The six count-chips, IMMEDIATELY — Buildings / Users / Contacts /
 *      Pricing / Extra work / Tickets, each routing to its sub-page.
 *   3. A dashboard row of live operational numbers from the new
 *      `/summary/` endpoint: open tickets, open extra work, outstanding
 *      invoiced.
 *   4. About and Linked buildings SIDE BY SIDE — each was spending a
 *      full-width card on half a card of content.
 *
 * Sprint 154 §A removed the quicklink grid that used to repeat the SAME
 * six destinations at the bottom of the page as icon-and-description
 * cards. Each chip now carries all four things the pair used to split
 * between them — icon, count, name, description — so a destination
 * appears exactly once, driven off one `chips` array rather than two
 * independently-maintained lists.
 *
 * Gone: the `section-explainer` paragraph (the chips say it better) and
 * the Facturatie section, which moved to the Settings tab.
 *
 * Nothing on this page mutates a permission, a policy, or a per-building
 * access row — those affordances live exclusively on the Permissions
 * sub-page. The Playwright spec locks that contract.
 */
export function CustomerOverviewPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation("common");
  const { me } = useAuth();
  const isSuperAdmin = me?.role === "SUPER_ADMIN";

  const numericId = useMemo(() => {
    if (!id) return null;
    const parsed = Number(id);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  }, [id]);

  const [customer, setCustomer] = useState<CustomerAdmin | null>(null);
  const [providerCompany, setProviderCompany] = useState<CompanyAdmin | null>(
    null,
  );
  const [linkedBuildings, setLinkedBuildings] = useState<
    CustomerBuildingMembership[]
  >([]);
  const [summary, setSummary] = useState<CustomerSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const reactivateDialogRef = useRef<ConfirmDialogHandle>(null);
  const [actionBusy, setActionBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    if (numericId === null) {
      queueMicrotask(() => {
        if (!cancelled) setError(t("bm_customer_detail.invalid_id"));
      });
      return () => {
        cancelled = true;
      };
    }
    setLoading(true); // eslint-disable-line react-hooks/set-state-in-effect
    setError("");
    // Sprint 153: THREE reads, down from five. The per-module counts
    // that used to be `listCustomerUsers(...).count` /
    // `listCustomerContacts(...).length` / `listCustomerPrices(...)
    // .length` now arrive from the one `/summary/` call, which also
    // brings the ticket / extra-work / invoice numbers the page needs.
    // The buildings list is still fetched in full because the linked-
    // buildings card renders names, not just a count.
    Promise.all([
      getCustomer(numericId),
      listCustomerBuildings(numericId).catch(() => ({
        count: 0,
        next: null,
        previous: null,
        results: [],
      })),
      // A summary failure degrades the dashboard to em dashes; it must
      // not take the whole page down.
      getCustomerSummary(numericId).catch(() => null),
    ])
      .then(([customerData, buildingsResponse, summaryData]) => {
        if (cancelled) return;
        setCustomer(customerData);
        setLinkedBuildings(buildingsResponse.results);
        setSummary(summaryData);
        // Provider company name is informational.
        getCompany(customerData.company)
          .then((company) => {
            if (!cancelled) setProviderCompany(company);
          })
          .catch(() => {
            if (!cancelled) setProviderCompany(null);
          });
      })
      .catch((err) => {
        if (!cancelled) setError(getApiError(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [numericId, t]);

  async function handleConfirmReactivate() {
    if (numericId === null) return;
    setActionBusy(true);
    setError("");
    try {
      await reactivateCustomer(numericId);
      reactivateDialogRef.current?.close();
      navigate("/admin/customers?reactivated=ok", { replace: true });
    } catch (err) {
      setError(getApiError(err));
      reactivateDialogRef.current?.close();
    } finally {
      setActionBusy(false);
    }
  }

  const customerName = customer?.name ?? "";
  const isActive = customer?.is_active ?? true;
  const buildingsCount = linkedBuildings.length;

  const headerActions = customer ? (
    <>
      {!isActive && isSuperAdmin && (
        <button
          type="button"
          className="btn btn-primary btn-sm"
          data-testid="reactivate-button"
          onClick={() => reactivateDialogRef.current?.open()}
        >
          {t("admin_form.reactivate")}
        </button>
      )}
      <Link
        to={`/admin/customers/${customer.id}/edit`}
        className="btn btn-secondary btn-sm"
        data-testid="customer-overview-edit-basics"
      >
        {t("customer_view.overview.edit_basics")}
      </Link>
    </>
  ) : null;

  // Mirror the languageLabel helper from CompanyDetailPage (Sprint 29.3).
  // Falls back to the raw code when the language isn't one of the two
  // bundled options.
  const languageLabel = (() => {
    if (!customer) return "";
    if (customer.language === "nl") {
      return `${t("language_dutch")} (nl)`;
    }
    if (customer.language === "en") {
      return `${t("language_english")} (en)`;
    }
    return customer.language;
  })();

  // A `null` count means the module is not readable by this operator —
  // render an em dash, never a zero. See `CustomerSummary` in types.ts.
  const chipValue = (value: number | null | undefined) =>
    value === null || value === undefined ? "—" : value;

  // Sprint 154 §A — the six (now seven) destinations, ONCE. Driven off
  // one array so a chip cannot exist with a count but no description, or
  // a destination appear twice with two different labels — which is what
  // the separate stat-strip + quicklink-grid pair had drifted into.
  //
  // `value: undefined` means "this chip has no count", which is
  // different from `null` ("there is a count but it is not yours to
  // read"). Permissions is the only one: there is no countable thing
  // behind it, so it renders with no number at all rather than a 0.
  const chips = customer
    ? [
        {
          testId: "customer-overview-stat-buildings",
          path: "buildings",
          Icon: MapPin,
          label: t("customer_view.overview.stat_linked_buildings"),
          description: t("customer_view.overview.quicklink_buildings_desc"),
          value:
            summary?.linked_building_count ?? customer.linked_building_count,
        },
        {
          testId: "customer-overview-stat-users",
          path: "users",
          Icon: UserCog,
          label: t("customer_view.overview.stat_customer_users"),
          description: t("customer_view.overview.quicklink_users_desc"),
          value: summary?.user_count ?? customer.user_count,
        },
        {
          testId: "customer-overview-stat-contacts",
          path: "contacts",
          Icon: Mail,
          label: t("customer_view.overview.stat_contacts"),
          description: t("customer_view.overview.quicklink_contacts_desc"),
          value: summary?.contact_count ?? customer.contact_count,
        },
        {
          testId: "customer-overview-stat-pricing",
          path: "pricing",
          Icon: Tag,
          label: t("customer_view.overview.stat_pricing"),
          description: t("customer_view.overview.quicklink_pricing_desc"),
          value: summary?.pricing_rule_count,
        },
        // Sprint 168 §6 — the Contracts chip is GONE. It made eight
        // chips, and eight wrap onto a second row, which broke the
        // single-row strip this component exists to keep. The owner
        // asked for a contracts PAGE for the customer, not a chip: the
        // page and its sidebar entry both stay, and this strip is back
        // to seven on one row. A chip with no count was the weakest of
        // the eight anyway — it carried a link and nothing else.
        {
          testId: "customer-overview-stat-extra-work",
          path: "extra-work",
          Icon: Receipt,
          label: t("customer_view.overview.stat_extra_work"),
          description: t("customer_view.overview.quicklink_extra_work_desc"),
          value: summary?.extra_work_count,
        },
        {
          testId: "customer-overview-stat-tickets",
          path: "tickets",
          Icon: Ticket,
          label: t("customer_view.overview.stat_tickets"),
          description: t("customer_view.overview.quicklink_tickets_desc"),
          value: summary?.ticket_count,
        },
        {
          testId: "customer-overview-stat-permissions",
          path: "permissions",
          Icon: ShieldCheck,
          label: t("customer_view.overview.quicklink_permissions"),
          description: t("customer_view.overview.quicklink_permissions_desc"),
          value: undefined,
        },
      ]
    : [];

  return (
    <div data-testid="customer-overview-page">
      <CustomerSubPageHeader
        customerName={customerName}
        isActive={isActive}
        actions={headerActions}
      />

      {error && (
        <div className="alert-error" style={{ marginBottom: 16 }} role="alert">
          {error}
        </div>
      )}

      {loading && !customer ? (
        <div className="loading-bar">
          <div className="loading-bar-fill" />
        </div>
      ) : customer ? (
        <>
          {/* 1. The chips — the page's ONE navigation surface.
              Sprint 154 §A: the quicklink grid that used to repeat these
              same six destinations at the bottom of the page is gone.
              Each chip now carries everything both used to say between
              them — icon, count, name and the one-line description —
              so a destination appears exactly once. */}
          <div
            className="summary-grid summary-grid-chips summary-grid-chips-one-row"
            data-testid="customer-overview-stat-strip"
          >
            {chips.map((chip) => (
              <Link
                key={chip.testId}
                to={`/admin/customers/${customer.id}/${chip.path}`}
                className="summary-stat summary-stat-chip"
                data-testid={chip.testId}
              >
                <span className="summary-stat-chip-head">
                  <chip.Icon size={16} strokeWidth={2} aria-hidden="true" />
                  <span className="summary-stat-label">{chip.label}</span>
                </span>
                {/* Permissions has no count. It renders with NO number
                    rather than a 0, which would be a lie: there is no
                    countable thing behind it. */}
                {chip.value !== undefined && (
                  <span className="summary-stat-value">
                    {chipValue(chip.value)}
                  </span>
                )}
                <span className="summary-stat-meta">{chip.description}</span>
              </Link>
            ))}
          </div>

          {/* 2. The dashboard row. Numbers with a label, not links to
              nowhere: a null value renders an em dash and does NOT link,
              because there is no page behind it for this operator. */}
          <section
            className="card"
            data-testid="customer-overview-dashboard"
            style={{ marginBottom: 18 }}
          >
            <div className="section-head">
              <div>
                <div className="section-head-title">
                  {t("customer_view.overview.dashboard_title")}
                </div>
                <div className="section-head-sub">
                  {t("customer_view.overview.dashboard_sub")}
                </div>
              </div>
            </div>
            <div
              className="summary-grid"
              style={{
                gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
                margin: 0,
                padding: "14px 18px 18px",
              }}
            >
              <DashboardMetric
                testId="customer-overview-metric-open-tickets"
                label={t("customer_view.overview.metric_open_tickets")}
                value={summary?.open_ticket_count ?? null}
                meta={
                  summary?.ticket_count === null ||
                  summary?.ticket_count === undefined
                    ? t("customer_view.overview.metric_unreadable")
                    : t("customer_view.overview.metric_of_total", {
                        count: summary.ticket_count,
                      })
                }
                to={`/admin/customers/${customer.id}/tickets`}
              />
              <DashboardMetric
                testId="customer-overview-metric-open-extra-work"
                label={t("customer_view.overview.metric_open_extra_work")}
                value={summary?.open_extra_work_count ?? null}
                meta={
                  summary?.extra_work_count === null ||
                  summary?.extra_work_count === undefined
                    ? t("customer_view.overview.metric_unreadable")
                    : t("customer_view.overview.metric_of_total", {
                        count: summary.extra_work_count,
                      })
                }
                to={`/admin/customers/${customer.id}/extra-work`}
              />
              <DashboardMetric
                testId="customer-overview-metric-unpaid-invoices"
                label={t("customer_view.overview.metric_unpaid_invoices")}
                value={
                  summary?.unpaid_invoice_total == null
                    ? null
                    : formatEuro(summary.unpaid_invoice_total)
                }
                meta={
                  summary?.unpaid_invoice_count == null
                    ? t("customer_view.overview.metric_unreadable")
                    : t("customer_view.overview.metric_sent_invoices", {
                        count: summary.unpaid_invoice_count,
                      })
                }
                to={`/admin/customers/${customer.id}/invoices`}
              />
            </div>
          </section>

          {/* 3. About + Linked buildings, side by side. */}
          <div className="customer-overview-split">
            <section
              className="card"
              data-testid="customer-overview-about-card"
              style={{ padding: "20px 22px" }}
            >
              <div className="section-head" style={{ marginBottom: 8 }}>
                <div>
                  <div className="section-head-title">
                    {t("customer_view.overview.about_title")}
                  </div>
                  <div className="section-head-sub">
                    {t("customer_view.overview.about_desc")}
                  </div>
                </div>
              </div>

              <div className="detail-field-row">
                <div className="detail-field-label">
                  {t("customer_view.overview.field_company")}
                </div>
                <div className="detail-field-value">
                  {providerCompany ? (
                    <Link to={`/admin/companies/${customer.company}`}>
                      {providerCompany.name}
                    </Link>
                  ) : (
                    <span className="muted-empty">—</span>
                  )}
                </div>
              </div>
              <div className="detail-field-row">
                <div className="detail-field-label">
                  {t("customer_view.overview.field_contact_email")}
                </div>
                <div className="detail-field-value">
                  {customer.contact_email ? (
                    <a href={`mailto:${customer.contact_email}`}>
                      {customer.contact_email}
                    </a>
                  ) : (
                    <span className="muted-empty">—</span>
                  )}
                </div>
              </div>
              <div className="detail-field-row">
                <div className="detail-field-label">
                  {t("customer_view.overview.field_phone")}
                </div>
                <div className="detail-field-value">
                  {customer.phone ? (
                    <a href={`tel:${customer.phone}`}>{customer.phone}</a>
                  ) : (
                    <span className="muted-empty">—</span>
                  )}
                </div>
              </div>
              <div className="detail-field-row">
                <div className="detail-field-label">
                  {t("customer_view.overview.field_language")}
                </div>
                <div className="detail-field-value">{languageLabel}</div>
              </div>
              <div className="detail-field-row">
                <div className="detail-field-label">
                  {t("customer_view.overview.field_status")}
                </div>
                <div className="detail-field-value">
                  {isActive ? (
                    <span className="cell-tag cell-tag-open">
                      <i />
                      {t("customer_view.overview.status_active")}
                    </span>
                  ) : (
                    <span className="cell-tag cell-tag-closed">
                      <i />
                      {t("customer_view.overview.status_inactive")}
                    </span>
                  )}
                </div>
              </div>
            </section>

            <div
              className="card"
              data-testid="customer-overview-buildings-preview"
            >
              <div className="section-head">
                <div className="section-head-title">
                  {t("customer_view.overview.buildings_preview_title")}
                </div>
                {/* Sprint 153 §4.3 — the view-all link is ALWAYS offered
                    now, not only past five rows. */}
                {buildingsCount > 0 && (
                  <Link
                    to={`/admin/customers/${customer.id}/buildings`}
                    className="btn btn-ghost btn-sm"
                    data-testid="customer-overview-buildings-view-all"
                  >
                    {t("customer_view.overview.buildings_preview_view_all", {
                      count: buildingsCount,
                    })}
                  </Link>
                )}
              </div>
              <div style={{ padding: "14px 18px 18px" }}>
                {/* BoundedList replaces the hand-rolled `.slice(0, 5)`.
                    Same rule (CLAUDE.md §8 — no unbounded server-
                    collection list), but the app-wide primitive, so the
                    scroll cap and the overflow count come for free. */}
                <BoundedList
                  size="sm"
                  count={buildingsCount}
                  ariaLabel={t("customer_view.overview.buildings_list_label")}
                  testIdPrefix="customer-overview-buildings"
                  emptyState={
                    <p className="muted small">
                      {t("customer_view.overview.buildings_preview_empty")}
                    </p>
                  }
                >
                  {/* Sprint 155 §2 — the card used to show a name and a
                      city and stop, so its right-hand half was visibly
                      empty next to About. It now carries the full
                      address line, what is at that building, and an
                      inactive marker — every field annotated on the row
                      the card already fetched, so filling it costs no
                      extra request (`test_sprint155_linked_buildings`
                      pins that with assertNumQueries).

                      The row is a LINK to the building. The prompt said
                      Sprint 154 had already made it one; it had not —
                      154 §G.3 added the click-through on the customer's
                      Buildings SUB-PAGE, and this preview card was
                      still plain divs. Adding it here rather than
                      "keeping" it. */}
                  <div className="bld-list">
                    {linkedBuildings.map((link) => (
                      <Link
                        key={link.id}
                        to={`/admin/buildings/${link.building_id}`}
                        className="linked-building-row"
                        data-testid={`customer-overview-building-${link.building_id}`}
                      >
                        <LinkedBuildingIdentity link={link} />
                        <LinkedBuildingCounts link={link} />
                      </Link>
                    ))}
                  </div>
                </BoundedList>
              </div>
            </div>
          </div>

          <ConfirmDialog
            ref={reactivateDialogRef}
            title={t("customer_form.dialog_reactivate_title", {
              name: customerName,
            })}
            body={t("customer_form.dialog_reactivate_body")}
            confirmLabel={t("admin_form.reactivate")}
            onConfirm={handleConfirmReactivate}
            busy={actionBusy}
          />
        </>
      ) : null}
    </div>
  );
}

/**
 * One number on the operational dashboard row. When `value` is null the
 * module is not readable by this operator: render an em dash and do NOT
 * link, because there is no page behind it for them.
 */
function DashboardMetric({
  label,
  value,
  meta,
  to,
  testId,
}: {
  label: string;
  value: number | string | null;
  meta: string;
  to: string;
  testId: string;
}) {
  const body = (
    <>
      <span className="summary-stat-label">{label}</span>
      <span className="summary-stat-value">{value ?? "—"}</span>
      <span className="summary-stat-meta">{meta}</span>
    </>
  );
  if (value === null) {
    return (
      <div className="summary-stat" data-testid={testId}>
        {body}
      </div>
    );
  }
  return (
    <Link to={to} className="summary-stat" data-testid={testId}>
      {body}
    </Link>
  );
}

/**
 * Format the decimal STRING the summary endpoint returns. Parsing is for
 * display only — grouping and the decimal separator; the string from the
 * server stays the authority for the amount. An unparseable value is
 * shown verbatim rather than as NaN.
 */
function formatEuro(decimalString: string): string {
  const parsed = Number(decimalString);
  if (!Number.isFinite(parsed)) return decimalString;
  return new Intl.NumberFormat("nl-NL", {
    style: "currency",
    currency: "EUR",
  }).format(parsed);
}
