import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  downloadDimensionExport,
  type DimensionExportFormat,
  type ReportFilters,
} from "../../../api/reports";

export interface ExportButtonsProps {
  dimension: "type" | "customer" | "building";
  filters: ReportFilters;
  disabled?: boolean;
}

/**
 * Two-button row (Export CSV / Export PDF) used by the Sprint-5
 * dimension charts. Each click downloads the file via a programmatic
 * <a download> click so the browser bypasses Vite's HTML-routing and
 * the existing axios JWT interceptor still attaches Authorization.
 */
export function ExportButtons({ dimension, filters, disabled }: ExportButtonsProps) {
  const { t } = useTranslation("reports");
  const [busy, setBusy] = useState<DimensionExportFormat | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handle = async (format: DimensionExportFormat) => {
    setError(null);
    setBusy(format);
    try {
      await downloadDimensionExport(dimension, format, filters);
    } catch {
      setError(t("export_error"));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div style={{ display: "flex", gap: 8, marginTop: 12, alignItems: "center" }}>
      <button
        type="button"
        className="btn btn-secondary btn-sm"
        onClick={() => handle("csv")}
        disabled={disabled || busy !== null}
        data-testid={`export-csv-${dimension}`}
      >
        {busy === "csv" ? t("export_busy") : t("export_csv")}
      </button>
      <button
        type="button"
        className="btn btn-secondary btn-sm"
        onClick={() => handle("pdf")}
        disabled={disabled || busy !== null}
        data-testid={`export-pdf-${dimension}`}
      >
        {busy === "pdf" ? t("export_busy") : t("export_pdf")}
      </button>
      {error && (
        <span className="muted small" style={{ color: "var(--red, #b91c1c)" }}>
          {error}
        </span>
      )}
    </div>
  );
}
