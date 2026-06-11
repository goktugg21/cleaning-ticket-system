// M2 P4 — "Credentials" card on UserFormPage (STAFF targets only).
//
// Compact list + drill-in modal (NO accordion — Addendum A.2 locked
// UX). Each row: type, visibility badge, expiry summary, paperclip
// when a document is attached, grant count. Click -> StaffCredentialModal
// keyed by credential id so its prop-derived state never resyncs.
import { useEffect, useState } from "react";
import { Paperclip, Plus } from "lucide-react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../api/client";
import { listCredentials } from "../../api/staffCredentials";
import type { StaffCredential } from "../../api/staffCredentials";
import { EmptyState } from "../../components/EmptyState";

import { StaffCredentialModal } from "./StaffCredentialModal";

export interface StaffCredentialsSectionProps {
  userId: number;
  canEdit: boolean;
}

export function StaffCredentialsSection({
  userId,
  canEdit,
}: StaffCredentialsSectionProps) {
  const { t } = useTranslation("staff_credentials");

  const [rows, setRows] = useState<StaffCredential[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<StaffCredential | "new" | null>(
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
        const data = await listCredentials(userId);
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
      const data = await listCredentials(userId);
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
      data-testid="staff-credentials-section"
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
          <h3 className="section-title">{t("section.credentials_title")}</h3>
          <p className="muted small" style={{ marginBottom: 12 }}>
            {t("section.credentials_desc")}
          </p>
        </div>
        {canEdit && (
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={() => setEditing("new")}
            data-testid="credential-add-button"
          >
            <Plus size={14} strokeWidth={2.2} />
            {t("section.add_credential")}
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
          title={t("section.empty_credentials_title")}
          description={t("section.empty_credentials_desc")}
          testId="credentials-empty"
        />
      ) : (
        <div role="list">
          {rows.map((row) => (
            <button
              type="button"
              role="listitem"
              key={row.id}
              onClick={() => setEditing(row)}
              data-testid={`credential-row-${row.id}`}
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
                {t(`type.${row.credential_type}`)}
              </span>
              <span className="cell-tag cell-tag-open">
                <i />
                {t(`visibility.${row.visibility_level}`)}
              </span>
              <span className="muted small">
                {row.expiry_date
                  ? t("summary.expires", { date: row.expiry_date })
                  : t("summary.no_expiry")}
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
        <StaffCredentialModal
          key={editing === "new" ? "new" : editing.id}
          userId={userId}
          credential={editing === "new" ? null : editing}
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
