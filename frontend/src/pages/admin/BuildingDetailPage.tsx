import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Users } from "lucide-react";


import { getApiError } from "../../api/client";
import {
  deactivateBuilding,
  getBuilding,
  getCompany,
  listBuildingManagers,
  reactivateBuilding,
} from "../../api/admin";
import type {
  BuildingAdmin,
  BuildingManagerMembership,
  CompanyAdmin,
} from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../components/ConfirmDialog";
import { EmptyState } from "../../components/EmptyState";
import { PageHeader } from "../../components/PageHeader";
import { useSavedBanner } from "../../hooks/useSavedBanner";

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
  const { t, i18n } = useTranslation("common");

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

  const dateLocale = i18n.language === "nl" ? "nl-NL" : "en-US";

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

          <section
            className="card"
            data-testid="building-detail-managers-card"
            style={{ padding: "20px 22px" }}
          >
            <div className="section-head" style={{ marginBottom: 8 }}>
              <div>
                <div className="section-head-title">
                  {t("building_detail.managers_title")}
                </div>
                <div className="section-head-sub">
                  {t("building_detail.managers_desc")}
                </div>
              </div>
            </div>

            {members.length === 0 ? (
              <EmptyState
                icon={Users}
                title={t("building_detail.managers_empty")}
                compact
                testId="building-detail-managers-empty"
              />
            ) : (
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>{t("users.col_email")}</th>
                      <th>{t("users.col_full_name")}</th>
                      <th>{t("admin_form.col_assigned")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {members.map((membership) => (
                      <tr key={membership.id}>
                        <td className="td-subject">{membership.user_email}</td>
                        <td>{membership.user_full_name || "—"}</td>
                        <td className="td-date">
                          {new Date(
                            membership.assigned_at,
                          ).toLocaleDateString(dateLocale)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

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
