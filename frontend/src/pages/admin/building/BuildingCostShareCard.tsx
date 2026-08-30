import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, getApiError } from "../../../api/client";

/**
 * Sprint 185 E §2 — who pays which share of a shared building.
 *
 * ## Why the whole division is edited and saved at once
 *
 * The rule is that the shares sum to exactly 100, which is a condition
 * over the SET. Editing one row at a time cannot satisfy it — going from
 * two tenants to three has to pass through a state that does not sum to
 * 100 — so the endpoint takes the whole set and so does this card. The
 * total is shown live and Save is refused until it reads 100, which
 * means the operator sees the arithmetic before the server does.
 *
 * ## Why the customers are a fixed list
 *
 * A share can only go to a customer that operates at this building
 * (`CustomerBuildingMembership`); the server refuses anything else. So
 * the picker offers exactly those, and the operator cannot compose a
 * division the server will reject on a ground they cannot see.
 *
 * An EMPTY division is a legitimate and meaningful state: the building
 * is not shared, and its work is billed in full to the customer whose
 * melding it is — exactly as it was before this sprint existed.
 */
export interface CostShareRow {
  id?: number;
  customer: number;
  customer_name?: string;
  share_pct: string;
}

export function BuildingCostShareCard({
  buildingId,
  customers,
  canEdit,
}: {
  buildingId: number;
  /** The customers linked to THIS building — the only ones the server
   *  will accept a share for. */
  customers: { id: number; name: string }[];
  canEdit: boolean;
}) {
  const { t } = useTranslation("common");
  const [rows, setRows] = useState<CostShareRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [banner, setBanner] = useState("");

  useEffect(() => {
    let cancelled = false;
    api
      .get<{ results: CostShareRow[] }>(`/buildings/${buildingId}/cost-shares/`)
      .then((response) => {
        if (cancelled) return;
        setRows(response.data.results);
        setError("");
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
  }, [buildingId]);

  // Live, and in the same arithmetic the server uses — the operator
  // should never press Save to discover they typed 90.
  const total = rows.reduce(
    (sum, row) => sum + (Number(row.share_pct) || 0),
    0,
  );
  const balanced = rows.length === 0 || Math.abs(total - 100) < 0.005;

  const available = customers.filter(
    (customer) => !rows.some((row) => row.customer === customer.id),
  );

  function update(index: number, patch: Partial<CostShareRow>) {
    setRows((current) =>
      current.map((row, i) => (i === index ? { ...row, ...patch } : row)),
    );
  }

  async function save() {
    setBusy(true);
    setError("");
    setBanner("");
    try {
      const response = await api.put<{ results: CostShareRow[] }>(
        `/buildings/${buildingId}/cost-shares/`,
        {
          shares: rows.map((row) => ({
            customer: row.customer,
            share_pct: row.share_pct,
          })),
        },
      );
      setRows(response.data.results);
      setBanner(t("cost_shares.saved"));
    } catch (err) {
      // The server's own message, verbatim: it names the number the
      // operator typed, which is more useful than a generic refusal.
      setError(getApiError(err));
    } finally {
      setBusy(false);
    }
  }

  /* P-4 (Part F) — the split is ADVANCED. Outside the fold: one calm
     sentence (unsplit: "All work here bills to the ticket's own
     customer"; split: who pays what). The form, the percentages and
     Save live inside the fold only. */
  const splitSentence =
    rows.length === 0
      ? t("cost_shares.unsplit_sentence")
      : t("cost_shares.split_sentence", {
          shares: rows
            .map(
              (row) =>
                `${row.customer_name || customers.find((c) => c.id === row.customer)?.name || row.customer} ${Number(row.share_pct)}%`,
            )
            .join(" · "),
        });

  return (
    <details
      className="action-fold card card-detail-pad"
      style={{ marginBottom: 16 }}
      data-testid="building-cost-shares"
    >
      <summary className="form-fold-summary" data-testid="building-cost-shares-summary">
        {splitSentence}
        {canEdit && <span className="form-fold-summary-value">{t("cost_shares.change")}</span>}
      </summary>
      <div className="section-head" style={{ marginBottom: 8, marginTop: 10 }}>
        <div>
          <div className="section-head-title">{t("cost_shares.title")}</div>
          <div className="section-head-sub">{t("cost_shares.desc")}</div>
        </div>
      </div>

      {error && (
        <div className="alert-error" role="alert" style={{ marginBottom: 12 }}>
          {error}
        </div>
      )}
      {banner && (
        <div className="alert-info" role="status" style={{ marginBottom: 12 }}>
          {banner}
        </div>
      )}

      {loading ? (
        <div className="loading-bar">
          <div className="loading-bar-fill" />
        </div>
      ) : rows.length === 0 ? (
        <p className="muted small" data-testid="building-cost-shares-empty">
          {t("cost_shares.empty")}
        </p>
      ) : (
        <div className="table-wrap">
          <table className="data-table data-table-dense">
            <thead>
              <tr>
                <th>{t("cost_shares.col_customer")}</th>
                <th style={{ textAlign: "right" }}>
                  {t("cost_shares.col_share")}
                </th>
                <th aria-label={t("cost_shares.remove_row")} />
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={row.customer}>
                  <td className="td-subject">
                    {row.customer_name ||
                      customers.find((c) => c.id === row.customer)?.name ||
                      row.customer}
                  </td>
                  <td style={{ textAlign: "right" }}>
                    <input
                      className="field-input"
                      type="number"
                      min="0.01"
                      max="100"
                      step="0.01"
                      style={{ maxWidth: 120, textAlign: "right" }}
                      value={row.share_pct}
                      disabled={!canEdit || busy}
                      onChange={(event) =>
                        update(index, { share_pct: event.target.value })
                      }
                      data-testid={`cost-share-input-${row.customer}`}
                    />
                  </td>
                  <td>
                    {canEdit && (
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        disabled={busy}
                        onClick={() =>
                          setRows((current) =>
                            current.filter((_, i) => i !== index),
                          )
                        }
                      >
                        {t("cost_shares.remove_row")}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {canEdit && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            marginTop: 12,
            flexWrap: "wrap",
          }}
        >
          <span
            className={balanced ? "muted small" : "small"}
            style={balanced ? undefined : { color: "var(--red)" }}
            data-testid="cost-shares-total"
          >
            {t("cost_shares.total", { total: total.toFixed(2) })}
          </span>
          {!balanced && (
            <span className="small" style={{ color: "var(--red)" }}>
              {t("cost_shares.must_total_100")}
            </span>
          )}
          <span style={{ flex: 1 }} />
          {available.length > 0 && (
            <select
              className="field-select"
              style={{ maxWidth: 220 }}
              value=""
              disabled={busy}
              onChange={(event) => {
                if (!event.target.value) return;
                const id = Number(event.target.value);
                setRows((current) => [
                  ...current,
                  { customer: id, share_pct: "0" },
                ]);
              }}
              data-testid="cost-shares-add"
            >
              <option value="">{t("cost_shares.add_row")}</option>
              {available.map((customer) => (
                <option key={customer.id} value={customer.id}>
                  {customer.name}
                </option>
              ))}
            </select>
          )}
          {rows.length > 0 && (
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              disabled={busy}
              onClick={() => setRows([])}
              data-testid="cost-shares-clear"
            >
              {t("cost_shares.clear")}
            </button>
          )}
          <button
            type="button"
            className="btn btn-primary btn-sm"
            disabled={busy || !balanced}
            onClick={() => void save()}
            data-testid="cost-shares-save"
          >
            {t("cost_shares.save")}
          </button>
        </div>
      )}
    </details>
  );
}
