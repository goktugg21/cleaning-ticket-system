import type { FormEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../../api/client";
import {
  addCustomerBuilding,
  getCustomer,
  listBuildings,
  listCustomerBuildings,
  removeCustomerBuilding,
} from "../../../api/admin";
import type {
  BuildingAdmin,
  CustomerAdmin,
  CustomerBuildingMembership,
} from "../../../api/types";
import { ConfirmDialog } from "../../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../../components/ConfirmDialog";

import { CustomerSubPageHeader } from "./CustomerSubPageHeader";

/**
 * Sprint 28 Batch 13 — Customer Buildings page (admin variant).
 *
 * Migrates the linked-buildings list + add/remove out of
 * `CustomerFormPage.tsx`. View-first: the table is the home state,
 * and the Add building dropdown is an inline form action.
 */
export function CustomerBuildingsPage() {
  const { id } = useParams();
  const { t, i18n } = useTranslation("common");
  const dateLocale = i18n.language === "nl" ? "nl-NL" : "en-US";

  const numericId = useMemo(() => {
    if (!id) return null;
    const parsed = Number(id);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  }, [id]);

  const [customer, setCustomer] = useState<CustomerAdmin | null>(null);
  const [linkedBuildings, setLinkedBuildings] = useState<
    CustomerBuildingMembership[]
  >([]);
  const [allCompanyBuildings, setAllCompanyBuildings] = useState<
    BuildingAdmin[]
  >([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [buildingLinkError, setBuildingLinkError] = useState("");
  const [buildingLinkBusy, setBuildingLinkBusy] = useState(false);
  const [selectedBuildingToLink, setSelectedBuildingToLink] = useState<
    number | ""
  >("");

  const unlinkBuildingDialogRef = useRef<ConfirmDialogHandle>(null);
  const [unlinkBuildingTarget, setUnlinkBuildingTarget] =
    useState<CustomerBuildingMembership | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (numericId === null) {
      queueMicrotask(() => {
        if (!cancelled) setLoadError(t("bm_customer_detail.invalid_id"));
      });
      return () => {
        cancelled = true;
      };
    }
    setLoading(true); // eslint-disable-line react-hooks/set-state-in-effect
    setLoadError("");
    getCustomer(numericId)
      .then(async (customerData) => {
        if (cancelled) return;
        setCustomer(customerData);
        const [linksResponse, companyBuildingsResponse] = await Promise.all([
          listCustomerBuildings(numericId),
          listBuildings({
            is_active: "true",
            page_size: 200,
            company: customerData.company,
          }),
        ]);
        if (cancelled) return;
        setLinkedBuildings(linksResponse.results);
        setAllCompanyBuildings(companyBuildingsResponse.results);
      })
      .catch((err) => {
        if (!cancelled) setLoadError(getApiError(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [numericId, t]);

  async function reloadLinks() {
    if (numericId === null || customer === null) return;
    try {
      const [linksResponse, companyBuildingsResponse] = await Promise.all([
        listCustomerBuildings(numericId),
        listBuildings({
          is_active: "true",
          page_size: 200,
          company: customer.company,
        }),
      ]);
      setLinkedBuildings(linksResponse.results);
      setAllCompanyBuildings(companyBuildingsResponse.results);
    } catch (err) {
      setBuildingLinkError(getApiError(err));
    }
  }

  async function handleAddBuildingLink(event: FormEvent) {
    event.preventDefault();
    if (numericId === null || selectedBuildingToLink === "") return;
    setBuildingLinkError("");
    setBuildingLinkBusy(true);
    try {
      await addCustomerBuilding(numericId, Number(selectedBuildingToLink));
      setSelectedBuildingToLink("");
      await reloadLinks();
    } catch (err) {
      setBuildingLinkError(getApiError(err));
    } finally {
      setBuildingLinkBusy(false);
    }
  }

  function openUnlinkBuildingDialog(link: CustomerBuildingMembership) {
    setUnlinkBuildingTarget(link);
    unlinkBuildingDialogRef.current?.open();
  }

  async function handleConfirmUnlinkBuilding() {
    if (numericId === null || !unlinkBuildingTarget) return;
    setBuildingLinkBusy(true);
    setBuildingLinkError("");
    try {
      await removeCustomerBuilding(
        numericId,
        unlinkBuildingTarget.building_id,
      );
      unlinkBuildingDialogRef.current?.close();
      setUnlinkBuildingTarget(null);
      await reloadLinks();
    } catch (err) {
      setBuildingLinkError(getApiError(err));
      unlinkBuildingDialogRef.current?.close();
    } finally {
      setBuildingLinkBusy(false);
    }
  }

  const linkedBuildingIds = useMemo(
    () => new Set(linkedBuildings.map((l) => l.building_id)),
    [linkedBuildings],
  );
  const availableBuildingsToLink = useMemo(
    () => allCompanyBuildings.filter((b) => !linkedBuildingIds.has(b.id)),
    [allCompanyBuildings, linkedBuildingIds],
  );

  const customerName = customer?.name ?? "";
  const isActive = customer?.is_active ?? true;
  const customerNameDisplay = customer?.name ?? "";

  return (
    <div data-testid="customer-buildings-page">
      <CustomerSubPageHeader
        customerName={customerName}
        isActive={isActive}
      />

      {loadError && (
        <div className="alert-error" style={{ marginBottom: 16 }} role="alert">
          {loadError}
        </div>
      )}

      {loading && !customer ? (
        <div className="loading-bar">
          <div className="loading-bar-fill" />
        </div>
      ) : customer ? (
        <>
          <p
            className="section-explainer"
            data-testid="customer-buildings-explainer"
          >
            {t("customer_view.buildings.explainer", { customer: customerName })}
          </p>

          <div
            className="summary-grid"
            style={{ gridTemplateColumns: "minmax(220px, 320px)" }}
            data-testid="customer-buildings-stat"
          >
            <div className="summary-stat" style={{ cursor: "default" }}>
              <span className="summary-stat-label">
                {t("customer_view.overview.stat_linked_buildings")}
              </span>
              <span className="summary-stat-value">{linkedBuildings.length}</span>
              <span className="summary-stat-meta">
                {t("customer_view.buildings.count_summary", {
                  count: linkedBuildings.length,
                })}
              </span>
            </div>
          </div>

        <section
          className="card"
          data-testid="section-customer-buildings"
          style={{ padding: "20px 22px" }}
        >
          <h3 className="section-title">
            {t("customer_view.buildings.title")}
          </h3>
          <p className="muted small" style={{ marginBottom: 12 }}>
            {t("customer_form.section_buildings_desc")}
          </p>

          {buildingLinkError && (
            <div
              className="alert-error"
              role="alert"
              style={{ marginBottom: 12 }}
            >
              {buildingLinkError}
            </div>
          )}

          <div className="table-wrap">
            <table
              className="data-table"
              data-testid="customer-buildings-table"
            >
              <thead>
                <tr>
                  <th>{t("admin.col_name")}</th>
                  <th>{t("admin.col_address")}</th>
                  <th>{t("customer_form.col_linked")}</th>
                  <th aria-label={t("admin.col_actions")} />
                </tr>
              </thead>
              <tbody>
                {linkedBuildings.map((link) => (
                  <tr key={link.id}>
                    <td className="td-subject">{link.building_name}</td>
                    <td>{link.building_address || "—"}</td>
                    <td className="td-date">
                      {new Date(link.created_at).toLocaleDateString(dateLocale)}
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        onClick={() => openUnlinkBuildingDialog(link)}
                        disabled={buildingLinkBusy}
                      >
                        {t("admin_form.remove")}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {linkedBuildings.length === 0 && (
              <p
                className="muted small"
                style={{ padding: "12px 0" }}
                data-testid="customer-buildings-empty"
              >
                {t("customer_form.no_buildings_linked")}
              </p>
            )}
          </div>

          <form
            onSubmit={handleAddBuildingLink}
            style={{
              display: "flex",
              gap: 8,
              marginTop: 12,
              alignItems: "flex-end",
            }}
          >
            <div className="field" style={{ flex: 1, marginBottom: 0 }}>
              <label className="field-label" htmlFor="add-customer-building">
                {t("customer_form.add_building")}
              </label>
              <select
                id="add-customer-building"
                className="field-select"
                value={
                  selectedBuildingToLink === ""
                    ? ""
                    : String(selectedBuildingToLink)
                }
                onChange={(event) => {
                  const v = event.target.value;
                  setSelectedBuildingToLink(v === "" ? "" : Number(v));
                }}
                disabled={
                  buildingLinkBusy || availableBuildingsToLink.length === 0
                }
              >
                <option value="">
                  {availableBuildingsToLink.length === 0
                    ? t("customer_form.no_eligible_buildings")
                    : t("customer_form.select_building_to_add")}
                </option>
                {availableBuildingsToLink.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
              </select>
            </div>
            <button
              type="submit"
              className="btn btn-primary"
              data-testid="building-link-add-button"
              disabled={buildingLinkBusy || selectedBuildingToLink === ""}
            >
              {buildingLinkBusy
                ? t("admin_form.adding")
                : t("admin_form.add")}
            </button>
          </form>

          <ConfirmDialog
            ref={unlinkBuildingDialogRef}
            title={t("customer_form.dialog_unlink_building_title", {
              building: unlinkBuildingTarget?.building_name ?? "",
              name: customerNameDisplay,
            })}
            body={t("customer_form.dialog_unlink_building_body")}
            confirmLabel={t("admin_form.remove")}
            onConfirm={handleConfirmUnlinkBuilding}
            onCancel={() => setUnlinkBuildingTarget(null)}
            busy={buildingLinkBusy}
            destructive
          />
        </section>
        </>
      ) : null}
    </div>
  );
}
