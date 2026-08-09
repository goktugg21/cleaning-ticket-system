import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../../api/client";
import {
  bulkLinkBuildings,
  getCustomer,
  listAllBuildings,
  listCustomerBuildings,
} from "../../../api/admin";
import type {
  BuildingAdmin,
  CustomerAdmin,
  CustomerBuildingMembership,
} from "../../../api/types";
import { ConfirmDialog } from "../../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../../components/ConfirmDialog";
import { EntityPicker } from "../../../components/EntityPicker";
import { EditModeToggle } from "../../../components/EditModeToggle";
import {
  LinkedBuildingCounts,
  LinkedBuildingIdentity,
} from "../../../components/LinkedBuildingCell";
import { MultiSelectToolbar } from "../../../components/MultiSelectToolbar";
import { useEditMode } from "../../../lib/useEditMode";

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
  // Sprint 154 §G.1 — a LIST, not one id: the add is a multi-select.
  const [buildingsToLink, setBuildingsToLink] = useState<number[]>([]);
  // ...and the rows carry checkboxes so several can be unlinked at once.
  const [selectedLinkIds, setSelectedLinkIds] = useState<number[]>([]);

  const unlinkBuildingDialogRef = useRef<ConfirmDialogHandle>(null);

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
          listAllBuildings({
            is_active: "true",
            company: customerData.company,
          }),
        ]);
        if (cancelled) return;
        setLinkedBuildings(linksResponse.results);
        setAllCompanyBuildings(companyBuildingsResponse);
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
        listAllBuildings({
          is_active: "true",
          company: customer.company,
        }),
      ]);
      setLinkedBuildings(linksResponse.results);
      setAllCompanyBuildings(companyBuildingsResponse);
    } catch (err) {
      setBuildingLinkError(getApiError(err));
    }
  }

  // Sprint 154 §G.1 — ONE request for all of them, through the shared
  // bulk endpoint. The previous version issued one POST per building.
  async function handleAddBuildingLinks() {
    if (numericId === null || buildingsToLink.length === 0) return;
    setBuildingLinkError("");
    setBuildingLinkBusy(true);
    try {
      await bulkLinkBuildings({
        buildings: buildingsToLink,
        relation: "customers",
        targets: [numericId],
        mode: "link",
      });
      setBuildingsToLink([]);
      await reloadLinks();
    } catch (err) {
      setBuildingLinkError(getApiError(err));
    } finally {
      setBuildingLinkBusy(false);
    }
  }

  // Bulk unlink. The server cascades the per-user access revoke for each
  // pair — an orphaned CustomerUserBuildingAccess row still matches the
  // scope subquery, so skipping it would leave a customer user with
  // visibility on a building their customer is no longer linked to.
  async function handleConfirmUnlinkBuildings() {
    if (numericId === null || selectedLinkIds.length === 0) return;
    setBuildingLinkBusy(true);
    setBuildingLinkError("");
    try {
      const buildingIds = linkedBuildings
        .filter((l) => selectedLinkIds.includes(l.id))
        .map((l) => l.building_id);
      await bulkLinkBuildings({
        buildings: buildingIds,
        relation: "customers",
        targets: [numericId],
        mode: "unlink",
      });
      unlinkBuildingDialogRef.current?.close();
      setSelectedLinkIds([]);
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

  const allLinksSelected =
    linkedBuildings.length > 0 &&
    selectedLinkIds.length === linkedBuildings.length;

  const toggleLink = (linkId: number) =>
    setSelectedLinkIds((current) =>
      current.includes(linkId)
        ? current.filter((existing) => existing !== linkId)
        : [...current, linkId],
    );

  const toggleAllLinks = () =>
    setSelectedLinkIds(
      allLinksSelected ? [] : linkedBuildings.map((l) => l.id),
    );

  // Sprint 155 §4 — the intent step. Outside edit mode this is a clean
  // read-only list whose rows still open the building; inside it the
  // checkboxes and the bulk unlink appear. The MODE is the shared
  // controller's, the selection stays local (see lib/useEditMode.ts).
  const edit = useEditMode(
    linkedBuildings.map((l) => l.id),
    { onExit: () => setSelectedLinkIds([]) },
  );

  const customerName = customer?.name ?? "";
  const isActive = customer?.is_active ?? true;

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
          <div
            style={{
              display: "flex",
              alignItems: "flex-start",
              justifyContent: "space-between",
              gap: 12,
            }}
          >
            <div>
              <h3 className="section-title">
                {t("customer_view.buildings.title")}
              </h3>
              <p className="muted small" style={{ marginBottom: 12 }}>
                {t("customer_form.section_buildings_desc")}
              </p>
            </div>
            {linkedBuildings.length > 0 && (
              <EditModeToggle
                editMode={edit.editMode}
                onToggle={edit.toggleMode}
                disabled={buildingLinkBusy}
                testId="customer-buildings-edit-mode-toggle"
              />
            )}
          </div>

          {buildingLinkError && (
            <div
              className="alert-error"
              role="alert"
              style={{ marginBottom: 12 }}
            >
              {buildingLinkError}
            </div>
          )}

          {edit.editMode && (
            <MultiSelectToolbar
              selectedCount={selectedLinkIds.length}
              onSelectAll={() =>
                setSelectedLinkIds(linkedBuildings.map((l) => l.id))
              }
              onClearAll={() => setSelectedLinkIds([])}
              disabled={buildingLinkBusy}
              actions={[
                {
                  key: "unlink",
                  label: t("customer_view.buildings.bulk_unlink"),
                  destructive: true,
                  onClick: () => unlinkBuildingDialogRef.current?.open(),
                },
              ]}
              testIdPrefix="customer-buildings-bulk"
            />
          )}

          <div className="table-wrap">
            <table
              className="data-table data-table-dense"
              data-testid="customer-buildings-table"
            >
              <thead>
                <tr>
                  {edit.editMode && (
                    <th className="th-select">
                      <input
                        type="checkbox"
                        checked={allLinksSelected}
                        onChange={toggleAllLinks}
                        disabled={
                          linkedBuildings.length === 0 || buildingLinkBusy
                        }
                        aria-label={t("customer_view.buildings.select_all")}
                        data-testid="customer-buildings-select-all"
                      />
                    </th>
                  )}
                  {/* Sprint 156 §3 — the same enriched row the customer
                      OVERVIEW card has carried since Sprint 155 §2. The
                      owner reported this list still looking half-empty
                      while the overview looked full; separate Name /
                      Address / City columns were why. Name and address
                      collapse into one identity cell and the counts get
                      their own column. */}
                  <th>{t("admin.col_name")}</th>
                  <th>{t("customer_view.overview.stat_linked_buildings")}</th>
                  <th>{t("customer_form.col_linked")}</th>
                  <th aria-label={t("admin.col_actions")} />
                </tr>
              </thead>
              <tbody>
                {linkedBuildings.map((link) => (
                  <tr key={link.id}>
                    {edit.editMode && (
                      <td className="td-select">
                        <input
                          type="checkbox"
                          checked={selectedLinkIds.includes(link.id)}
                          onChange={() => toggleLink(link.id)}
                          disabled={buildingLinkBusy}
                          aria-label={t("customer_view.buildings.select_row", {
                            name: link.building_name,
                          })}
                          data-testid={`customer-buildings-select-${link.id}`}
                        />
                      </td>
                    )}
                    {/* Sprint 154 §G.1 — the owner asked for this
                        explicitly: from a customer he must be able to
                        reach the building. Every row is a link now. */}
                    <td className="td-subject">
                      <Link
                        to={`/admin/buildings/${link.building_id}`}
                        data-testid={`customer-buildings-link-${link.building_id}`}
                        style={{ display: "inline-flex", minWidth: 0 }}
                      >
                        <LinkedBuildingIdentity link={link} />
                      </Link>
                    </td>
                    <td>
                      <LinkedBuildingCounts link={link} align="start" />
                    </td>
                    <td className="td-date">
                      {new Date(link.created_at).toLocaleDateString(dateLocale)}
                    </td>
                    <td>
                      <Link
                        className="btn btn-ghost btn-sm"
                        to={`/admin/buildings/${link.building_id}`}
                      >
                        {t("customer_view.buildings.open_building")}
                      </Link>
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

          {/* Sprint 154 §G.1 — a MULTI-select add. Linking six
              buildings used to be six round-trips; it is one request. */}
          <div style={{ marginTop: 14 }}>
            <div className="detail-field-label" style={{ marginBottom: 6 }}>
              {t("customer_form.add_building")}
            </div>
            <EntityPicker
              options={availableBuildingsToLink.map((b) => ({
                id: b.id,
                label: b.name,
                sublabel: [b.city, b.address].filter(Boolean).join(" — "),
              }))}
              selectedIds={buildingsToLink}
              onChange={setBuildingsToLink}
              disabled={buildingLinkBusy}
              emptyText={t("customer_form.no_eligible_buildings")}
              testIdPrefix="customer-buildings-add"
              size="sm"
            />
            <div
              style={{
                display: "flex",
                justifyContent: "flex-end",
                marginTop: 10,
              }}
            >
              <button
                type="button"
                className="btn btn-primary"
                data-testid="building-link-add-button"
                onClick={handleAddBuildingLinks}
                disabled={buildingLinkBusy || buildingsToLink.length === 0}
              >
                {buildingLinkBusy ? t("admin_form.adding") : t("admin_form.add")}
              </button>
            </div>
          </div>

          <ConfirmDialog
            ref={unlinkBuildingDialogRef}
            title={t("customer_view.buildings.bulk_unlink_title")}
            body={t("customer_view.buildings.bulk_unlink_body", {
              count: selectedLinkIds.length,
            })}
            confirmLabel={t("customer_view.buildings.bulk_unlink")}
            onConfirm={handleConfirmUnlinkBuildings}
            busy={buildingLinkBusy}
            destructive
          />
        </section>
        </>
      ) : null}
    </div>
  );
}
