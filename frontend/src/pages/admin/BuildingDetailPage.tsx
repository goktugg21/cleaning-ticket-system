import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";


import { getApiError } from "../../api/client";
import {
  deactivateBuilding,
  getBuilding,
  getBuildingSummary,
  getCompany,
  listAllUsersByRole,
  listBuildingContacts,
  listBuildingCustomers,
  listBuildingManagers,
  listBuildingStaff,
  listAllCustomers,
  listCustomerContacts,
  reactivateBuilding,
} from "../../api/admin";
import type {
  BuildingAdmin,
  BuildingContactRow,
  BuildingManagerMembership,
  BuildingStaffRow,
  BuildingSummary,
  CompanyAdmin,
  Contact,
  CustomerAdmin,
  CustomerBuildingMembership,
  UserAdmin,
} from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../components/ConfirmDialog";
import { PageHeader } from "../../components/PageHeader";
import { useSavedBanner } from "../../hooks/useSavedBanner";

import { BuildingRelationCard } from "./building/BuildingRelationCard";

/**
 * Sprint 29 Batch 29.4 — Building Detail page (read-only view).
 *
 * View-first per the 2026-05-15 stakeholder doc §3. `/admin/buildings/:id`
 * loads this page in read-only mode; an explicit role-gated Edit button
 * (top right) navigates to `/admin/buildings/:id/edit` which renders
 * the legacy `BuildingFormPage` form. SUPER_ADMIN may also Deactivate /
 * Reactivate from this page — those affordances moved verbatim from
 * the form page so the read-only surface still carries the lifecycle
 * actions an admin expects.
 *
 * The page intentionally does NOT mutate building fields or manager
 * memberships — those affordances live on the edit form. The Edit
 * button is gated to SUPER_ADMIN and to COMPANY_ADMINs that are
 * members of the building's company; BUILDING_MANAGER is blocked at
 * the route guard so does not reach this page at all.
 *
 * Mirrors `CompanyDetailPage` from Sprint 29 Batch 29.3.
 */
export function BuildingDetailPage() {
  const navigate = useNavigate();
  const { id } = useParams();
  const { t } = useTranslation("common");

  const { me } = useAuth();
  const isSuperAdmin = me?.role === "SUPER_ADMIN";

  const numericId = useMemo(() => {
    if (!id) return null;
    const parsed = Number(id);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  }, [id]);

  const [savedBanner] = useSavedBanner({
    saved: t("buildings.banner_saved"),
  });

  const [building, setBuilding] = useState<BuildingAdmin | null>(null);
  const [company, setCompany] = useState<CompanyAdmin | null>(null);
  const [members, setMembers] = useState<BuildingManagerMembership[]>([]);
  // Sprint 154 §G.2 — the other three linked sets, plus the dashboard
  // counts. Each fetch is individually defensive: one relation the
  // operator cannot read must not blank the whole page.
  const [customerLinks, setCustomerLinks] = useState<
    CustomerBuildingMembership[]
  >([]);
  const [staffLinks, setStaffLinks] = useState<BuildingStaffRow[]>([]);
  const [contactLinks, setContactLinks] = useState<BuildingContactRow[]>([]);
  const [summary, setSummary] = useState<BuildingSummary | null>(null);
  // Candidate universes for the four Add pickers.
  const [allCustomers, setAllCustomers] = useState<CustomerAdmin[]>([]);
  const [allManagers, setAllManagers] = useState<UserAdmin[]>([]);
  const [allStaff, setAllStaff] = useState<UserAdmin[]>([]);
  const [candidateContacts, setCandidateContacts] = useState<Contact[]>([]);
  const [relationsToken, setRelationsToken] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const deactivateDialogRef = useRef<ConfirmDialogHandle>(null);
  const reactivateDialogRef = useRef<ConfirmDialogHandle>(null);
  const [actionBusy, setActionBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    if (numericId === null) {
      queueMicrotask(() => {
        if (!cancelled) setError(t("building_detail.invalid_id"));
      });
      return () => {
        cancelled = true;
      };
    }
    setLoading(true); // eslint-disable-line react-hooks/set-state-in-effect
    setError("");
    // Tier 1: fetch the building and managers in parallel (managers is
    // defensive — a 403 there should not block the read view).
    Promise.all([
      getBuilding(numericId),
      listBuildingManagers(numericId).catch(() => ({
        count: 0,
        next: null,
        previous: null,
        results: [] as BuildingManagerMembership[],
      })),
    ])
      .then(async ([buildingData, membersResponse]) => {
        if (cancelled) return;
        setBuilding(buildingData);
        setMembers(membersResponse.results);
        // Tier 2: resolve the FK company name. BuildingAdmin only
        // carries the company id; defensive .catch so an admin who
        // can read the building but not the company still sees the
        // detail page (we render the bare id in that fallback).
        try {
          const companyData = await getCompany(buildingData.company);
          if (!cancelled) setCompany(companyData);
        } catch {
          /* swallow — the field row shows the id fallback */
        }
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

  // Sprint 154 §G.2 — the four relation sets + the summary counts +
  // the candidate universes. Bumping `relationsToken` refetches after a
  // card links or unlinks something.
  useEffect(() => {
    if (numericId === null) return;
    let cancelled = false;
    const company = building?.company;
    Promise.all([
      listBuildingCustomers(numericId).catch(() => []),
      listBuildingManagers(numericId)
        .then((r) => r.results)
        .catch(() => [] as BuildingManagerMembership[]),
      listBuildingStaff(numericId).catch(() => []),
      listBuildingContacts(numericId).catch(() => []),
      getBuildingSummary(numericId).catch(() => null),
      company === undefined
        ? Promise.resolve([] as CustomerAdmin[])
        : listAllCustomers({ is_active: "true", company }).catch(() => []),
      listAllUsersByRole("BUILDING_MANAGER").catch(() => [] as UserAdmin[]),
      listAllUsersByRole("STAFF").catch(() => [] as UserAdmin[]),
    ]).then(
      ([
        customersData,
        managersData,
        staffData,
        contactsData,
        summaryData,
        customerCandidates,
        managerCandidates,
        staffCandidates,
      ]) => {
        if (cancelled) return;
        setCustomerLinks(customersData);
        setMembers(managersData);
        setStaffLinks(staffData);
        setContactLinks(contactsData);
        setSummary(summaryData);
        setAllCustomers(customerCandidates);
        setAllManagers(managerCandidates);
        setAllStaff(staffCandidates);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [numericId, building?.company, relationsToken]);

  // Contact CANDIDATES are the contacts of the customers linked to this
  // building. There is no "all contacts" endpoint and there should not
  // be: a contact belongs to a customer, and a customer not served here
  // has no business being offered as a site contact. One request per
  // linked customer — a building has a handful, not hundreds.
  useEffect(() => {
    if (customerLinks.length === 0) return;
    let cancelled = false;
    Promise.all(
      customerLinks.map((link) =>
        listCustomerContacts(link.customer).catch(() => [] as Contact[]),
      ),
    ).then((lists) => {
      if (!cancelled) setCandidateContacts(lists.flat());
    });
    return () => {
      cancelled = true;
    };
  }, [customerLinks]);

  async function handleConfirmDeactivate() {
    if (numericId === null) return;
    setActionBusy(true);
    setError("");
    try {
      await deactivateBuilding(numericId);
      deactivateDialogRef.current?.close();
      navigate("/admin/buildings?deactivated=ok", { replace: true });
    } catch (err) {
      setError(getApiError(err));
      deactivateDialogRef.current?.close();
    } finally {
      setActionBusy(false);
    }
  }

  async function handleConfirmReactivate() {
    if (numericId === null) return;
    setActionBusy(true);
    setError("");
    try {
      await reactivateBuilding(numericId);
      reactivateDialogRef.current?.close();
      navigate("/admin/buildings?reactivated=ok", { replace: true });
    } catch (err) {
      setError(getApiError(err));
      reactivateDialogRef.current?.close();
    } finally {
      setActionBusy(false);
    }
  }

  // SUPER_ADMIN always; COMPANY_ADMIN only if this building's company is
  // in their membership set. The backend enforces this independently;
  // the UI gate is defence in depth and keeps the affordance honest.
  // BUILDING_MANAGER never sees Edit — they can't even reach this route
  // (AdminRoute blocks them), but the explicit role check below is the
  // belt-and-braces.
  const canEdit =
    me?.role === "SUPER_ADMIN" ||
    (me?.role === "COMPANY_ADMIN" &&
      building !== null &&
      me.company_ids.includes(building.company));

  const buildingName = building?.name ?? t("building_form.fallback");
  const isActive = building?.is_active ?? true;


  const companyLabel = (() => {
    if (!building) return "";
    if (company) return company.name;
    return t("buildings.company_fallback", { id: building.company });
  })();

  const headerActions = building ? (
    <>
      {!isActive && isSuperAdmin && (
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          data-testid="reactivate-button"
          onClick={() => reactivateDialogRef.current?.open()}
        >
          {t("admin_form.reactivate")}
        </button>
      )}
      {isActive && isSuperAdmin && (
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          data-testid="deactivate-button"
          onClick={() => deactivateDialogRef.current?.open()}
        >
          {t("admin_form.deactivate")}
        </button>
      )}
      {canEdit && (
        <Link
          to={`/admin/buildings/${building.id}/edit`}
          className="btn btn-primary btn-sm"
          data-testid="building-edit-link"
        >
          {t("building_detail.edit_button")}
        </Link>
      )}
    </>
  ) : null;

  return (
    <div data-testid="building-detail-page">
      <PageHeader
        backLink={{
          to: "/admin/buildings",
          label: t("building_form.back"),
        }}
        eyebrow={t("nav.admin_group")}
        title={buildingName}
        statusPill={
          !isActive ? (
            <span className="cell-tag cell-tag-closed">
              <i />
              {t("building_detail.status_inactive")}
            </span>
          ) : undefined
        }
        actions={headerActions}
      />

      {savedBanner && (
        <div className="alert-info" style={{ marginBottom: 16 }} role="status">
          {savedBanner}
        </div>
      )}

      {error && (
        <div className="alert-error" style={{ marginBottom: 16 }} role="alert">
          {error}
        </div>
      )}

      {loading && !building ? (
        <div className="loading-bar">
          <div className="loading-bar-fill" />
        </div>
      ) : building ? (
        <>
          {/* Sprint 154 §G.2 — the counts, from /summary/. A null value
              renders an em dash: `room_count` is ALWAYS null because this
              system has no room concept at all, and showing 0 would claim
              the building has none rather than that the idea does not
              exist here. */}
          <div
            className="summary-grid summary-grid-chips"
            data-testid="building-detail-stats"
          >
            {[
              { key: "rooms", label: t("building_detail.stat_rooms"), value: summary?.room_count },
              { key: "customers", label: t("building_detail.stat_customers"), value: summary?.customer_count },
              { key: "managers", label: t("building_detail.stat_managers"), value: summary?.manager_count },
              { key: "staff", label: t("building_detail.stat_staff"), value: summary?.staff_count },
              { key: "contacts", label: t("building_detail.stat_contacts"), value: summary?.contact_count },
              { key: "open-tickets", label: t("building_detail.stat_open_tickets"), value: summary?.open_ticket_count },
              { key: "open-extra-work", label: t("building_detail.stat_open_extra_work"), value: summary?.open_extra_work_count },
            ].map((stat) => (
              <div
                className="summary-stat"
                key={stat.key}
                style={{ cursor: "default" }}
                data-testid={`building-detail-stat-${stat.key}`}
              >
                <span className="summary-stat-label">{stat.label}</span>
                <span className="summary-stat-value">
                  {stat.value === null || stat.value === undefined
                    ? "—"
                    : stat.value}
                </span>
              </div>
            ))}
          </div>

          <section
            className="card"
            data-testid="building-detail-about-card"
            style={{ padding: "20px 22px", marginBottom: 16 }}
          >
            <div className="section-head" style={{ marginBottom: 8 }}>
              <div>
                <div className="section-head-title">
                  {t("building_detail.about_title")}
                </div>
                <div className="section-head-sub">
                  {t("building_detail.about_desc")}
                </div>
              </div>
            </div>

            <div className="detail-field-row">
              <div className="detail-field-label">
                {t("building_detail.field_company")}
              </div>
              <div className="detail-field-value">
                <Link to={`/admin/companies/${building.company}`}>
                  {companyLabel}
                </Link>
              </div>
            </div>
            <div className="detail-field-row">
              <div className="detail-field-label">
                {t("building_detail.field_name")}
              </div>
              <div className="detail-field-value">{building.name}</div>
            </div>
            <div className="detail-field-row">
              <div className="detail-field-label">
                {t("building_detail.field_address")}
              </div>
              <div
                className={`detail-field-value${
                  building.address ? "" : " muted-empty"
                }`}
              >
                {building.address || "—"}
              </div>
            </div>
            {/* Sprint 178 §1 — the building's kind, from this company's
                own catalog. Renders the em dash when unclassified, the
                same as every other optional field on this page. */}
            <div className="detail-field-row">
              <div className="detail-field-label">
                {t("building_detail.field_building_type")}
              </div>
              <div
                className={`detail-field-value${
                  building.building_type_name ? "" : " muted-empty"
                }`}
                data-testid="building-detail-building-type"
              >
                {building.building_type_name || "—"}
              </div>
            </div>
            <div className="detail-field-row">
              <div className="detail-field-label">
                {t("building_detail.field_city")}
              </div>
              <div
                className={`detail-field-value${
                  building.city ? "" : " muted-empty"
                }`}
              >
                {building.city || "—"}
              </div>
            </div>
            <div className="detail-field-row">
              <div className="detail-field-label">
                {t("building_detail.field_postal_code")}
              </div>
              <div
                className={`detail-field-value${
                  building.postal_code ? "" : " muted-empty"
                }`}
              >
                {building.postal_code || "—"}
              </div>
            </div>
            <div className="detail-field-row">
              <div className="detail-field-label">
                {t("building_detail.field_country")}
              </div>
              <div
                className={`detail-field-value${
                  building.country ? "" : " muted-empty"
                }`}
              >
                {building.country || "—"}
              </div>
            </div>
            <div className="detail-field-row">
              <div className="detail-field-label">
                {t("building_detail.field_status")}
              </div>
              <div className="detail-field-value">
                {isActive ? (
                  <span className="cell-tag cell-tag-open">
                    <i />
                    {t("building_detail.status_active")}
                  </span>
                ) : (
                  <span className="cell-tag cell-tag-closed">
                    <i />
                    {t("building_detail.status_inactive")}
                  </span>
                )}
              </div>
            </div>
          </section>

          {/* Sprint 154 §G.2 — the four sets of linked people, each
              manageable from here. None of these models are new; this is
              the direction that was missing. */}
          <BuildingRelationCard
            buildingId={building.id}
            relation="customers"
            title={t("building_detail.customers_title")}
            description={t("building_detail.customers_desc")}
            emptyText={t("building_detail.customers_empty")}
            rows={customerLinks.map((link) => ({
              linkId: link.id,
              targetId: link.customer,
              name: link.customer_name || String(link.customer),
              meta: link.building_city || undefined,
            }))}
            candidates={allCustomers
              .filter((c) => !customerLinks.some((l) => l.customer === c.id))
              .map((c) => ({
                id: c.id,
                label: c.name,
                sublabel: c.contact_email,
              }))}
            addTitle={t("building_detail.add_customers_title")}
            testIdPrefix="building-detail-customers"
            disabled={!canEdit}
            onChanged={() => setRelationsToken((n) => n + 1)}
          />

          <BuildingRelationCard
            buildingId={building.id}
            relation="managers"
            title={t("building_detail.managers_title")}
            description={t("building_detail.managers_desc")}
            emptyText={t("building_detail.managers_empty")}
            rows={members.map((m) => ({
              linkId: m.id,
              targetId: m.user_id,
              name: m.user_full_name || m.user_email,
              email: m.user_email,
            }))}
            candidates={allManagers
              .filter((u) => !members.some((m) => m.user_id === u.id))
              .map((u) => ({
                id: u.id,
                label: u.full_name || u.email,
                sublabel: u.email,
              }))}
            addTitle={t("building_detail.add_managers_title")}
            testIdPrefix="building-detail-managers"
            disabled={!canEdit}
            onChanged={() => setRelationsToken((n) => n + 1)}
          />

          <BuildingRelationCard
            buildingId={building.id}
            relation="staff"
            title={t("building_detail.staff_title")}
            description={t("building_detail.staff_desc")}
            emptyText={t("building_detail.staff_empty")}
            rows={staffLinks.map((row) => ({
              linkId: row.id,
              targetId: row.user_id,
              name: row.user_full_name || row.user_email,
              email: row.user_email,
              phone: row.user_phone,
            }))}
            candidates={allStaff
              .filter((u) => !staffLinks.some((r) => r.user_id === u.id))
              .map((u) => ({
                id: u.id,
                label: u.full_name || u.email,
                sublabel: u.email,
              }))}
            addTitle={t("building_detail.add_staff_title")}
            testIdPrefix="building-detail-staff"
            disabled={!canEdit}
            onChanged={() => setRelationsToken((n) => n + 1)}
          />

          <BuildingRelationCard
            buildingId={building.id}
            relation="contacts"
            title={t("building_detail.contacts_title")}
            description={t("building_detail.contacts_desc")}
            emptyText={t("building_detail.contacts_empty")}
            rows={contactLinks.map((row) => ({
              linkId: row.id,
              targetId: row.contact_id,
              name: row.full_name,
              email: row.email,
              phone: row.phone,
              meta: [row.role_label, row.customer_name]
                .filter(Boolean)
                .join(" — "),
            }))}
            candidates={candidateContacts
              .filter((c) => !contactLinks.some((r) => r.contact_id === c.id))
              .map((c) => ({
                id: c.id,
                label: c.full_name,
                sublabel: [c.role_label, c.email].filter(Boolean).join(" — "),
              }))}
            addTitle={t("building_detail.add_contacts_title")}
            testIdPrefix="building-detail-contacts"
            disabled={!canEdit}
            onChanged={() => setRelationsToken((n) => n + 1)}
          />

          <ConfirmDialog
            ref={deactivateDialogRef}
            title={t("building_form.dialog_deactivate_title", {
              name: buildingName,
            })}
            body={t("building_form.dialog_deactivate_body")}
            confirmLabel={t("admin_form.deactivate")}
            onConfirm={handleConfirmDeactivate}
            busy={actionBusy}
          />

          <ConfirmDialog
            ref={reactivateDialogRef}
            title={t("building_form.dialog_reactivate_title", {
              name: buildingName,
            })}
            body={t("building_form.dialog_reactivate_body")}
            confirmLabel={t("admin_form.reactivate")}
            onConfirm={handleConfirmReactivate}
            busy={actionBusy}
          />
        </>
      ) : null}
    </div>
  );
}
