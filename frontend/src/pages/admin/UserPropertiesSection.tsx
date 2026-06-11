// M2 P4 — "Custom properties" card on UserFormPage (ANY target user —
// staff AND customer users carry properties, SoT Addendum A.3.2).
// Same compact-list + drill-in shape as StaffCredentialsSection.
import { useEffect, useState } from "react";
import { Paperclip, Plus } from "lucide-react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../api/client";
import { listProperties } from "../../api/staffCredentials";
import type { CustomProfileProperty } from "../../api/staffCredentials";
import { EmptyState } from "../../components/EmptyState";

import { UserPropertyModal } from "./UserPropertyModal";

export interface UserPropertiesSectionProps {
  userId: number;
  targetIsStaff: boolean;
  canEdit: boolean;
}

export function UserPropertiesSection({
  userId,
  targetIsStaff,
  canEdit,
}: UserPropertiesSectionProps) {
  const { t } = useTranslation("staff_credentials");

  const [rows, setRows] = useState<CustomProfileProperty[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<CustomProfileProperty | "new" | null>(
    null,
  );

  // Initial load — all setState inside the async IIFE after the await
  // (the CustomerUserManageModal pattern; a named callback the effect
  // calls trips react-hooks/set-state-in-effect even when every
  // setState sits behind an await).
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await listProperties(userId);
        if (cancelled) return;
        setRows(data);
        setError("");
        setLoading(false);
      } catch (err) {
        if (!cancelled) {
          setError(getApiError(err));
          setLoading(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [userId]);

  // Post-mutation refresh (modal onChanged) — outside any effect.
  async function reload() {
    try {
      const data = await listProperties(userId);
      setRows(data);
      setError("");
    } catch (err) {
      setError(getApiError(err));
    }
  }

  return (
    <section
      className="card"
      style={{ marginTop: 16, padding: "20px 22px" }}
      data-testid="user-properties-section"
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
          <h3 className="section-title">{t("section.properties_title")}</h3>
          <p className="muted small" style={{ marginBottom: 12 }}>
            {t("section.properties_desc")}
          </p>
        </div>
        {canEdit && (
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={() => setEditing("new")}
            data-testid="property-add-button"
          >
            <Plus size={14} strokeWidth={2.2} />
            {t("section.add_property")}
          </button>
        )}
      </div>

      {error && (
        <div className="alert-error" role="alert" style={{ marginBottom: 12 }}>
          {error}
        </div>
      )}

      {loading ? (
        <div className="loading-bar">
          <div className="loading-bar-fill" />
        </div>
      ) : rows.length === 0 ? (
        <EmptyState
          compact
          title={t("section.empty_properties_title")}
          description={t("section.empty_properties_desc")}
          testId="properties-empty"
        />
      ) : (
        <div role="list">
          {rows.map((row) => (
            <button
              type="button"
              role="listitem"
              key={row.id}
              onClick={() => setEditing(row)}
              data-testid={`property-row-${row.id}`}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                width: "100%",
                textAlign: "left",
                background: "none",
                border: "none",
                borderTop: "1px solid var(--border)",
                padding: "10px 2px",
                cursor: "pointer",
                font: "inherit",
                color: "inherit",
              }}
            >
              <span style={{ fontWeight: 600, minWidth: 140 }}>
                {row.name}
              </span>
              <span className="cell-tag cell-tag-open">
                <i />
                {t(`visibility.${row.visibility_level}`)}
              </span>
              <span
                className="muted small"
                style={{
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                  maxWidth: 220,
                }}
              >
                {row.value}
              </span>
              <span
                style={{
                  marginLeft: "auto",
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 8,
                }}
              >
                {row.has_document && (
                  <Paperclip
                    size={14}
                    strokeWidth={2}
                    aria-label={t("summary.has_document")}
                  />
                )}
                {row.grants.length > 0 && (
                  <span className="muted small">
                    {t("summary.grant_count", { count: row.grants.length })}
                  </span>
                )}
              </span>
            </button>
          ))}
        </div>
      )}

      {editing !== null && (
        <UserPropertyModal
          key={editing === "new" ? "new" : editing.id}
          userId={userId}
          property={editing === "new" ? null : editing}
          targetIsStaff={targetIsStaff}
          canEdit={canEdit}
          onClose={() => setEditing(null)}
          onChanged={() => {
            void reload();
          }}
        />
      )}
    </section>
  );
}
