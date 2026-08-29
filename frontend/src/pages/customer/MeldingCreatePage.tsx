/**
 * FE-2 (Addendum D §D.5.1) — the customer melding flow.
 *
 * Three visible questions: WAAR (pre-selected when the account has
 * exactly one building; the Klant question does not exist — it is
 * derived from membership), WAT IS ER AAN DE HAND (one description),
 * FOTO (optional). Urgentie defaults to Normaal with a single "Spoed"
 * toggle. The SLA matrix, the second required description and the
 * category/room machinery are gone from this surface.
 *
 * The SERVER CONTRACT IS UNCHANGED: submission goes to the existing
 * POST /tickets/ with the fields it requires. The one description maps
 * onto that contract — its first line (clipped) becomes `title`, the
 * whole text `description`. "Spoed" maps to priority URGENT; default
 * NORMAL. Photos go to the existing attachments endpoint after create.
 *
 * Confirmation says what happens next in phase words (§D.2) and links
 * to the melding — no navigation into the provider console.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Camera, CheckCircle2, MapPin, Megaphone, Siren } from "lucide-react";

import { api, getApiError } from "../../api/client";
import { listAllBuildings, listAllCustomers } from "../../api/admin";
import type { Building, Customer } from "../../api/types";
import { PageHeader } from "../../components/PageHeader";
import { titleFrom } from "../../lib/meldingTitle";

const MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024;

export function MeldingCreatePage() {
  const { t } = useTranslation("common");

  const [buildings, setBuildings] = useState<Building[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");

  const [building, setBuilding] = useState<number | "">("");
  const [description, setDescription] = useState("");
  const [urgent, setUrgent] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [fileError, setFileError] = useState("");

  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const [createdId, setCreatedId] = useState<number | null>(null);
  const [attachmentWarning, setAttachmentWarning] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // The account's own buildings and customer(s). Both endpoints are
  // tenant-scoped server-side, so a CUSTOMER_USER receives exactly what
  // their memberships admit — this page adds no narrowing of its own.
  useEffect(() => {
    let cancelled = false;
    Promise.all([listAllBuildings(), listAllCustomers()])
      .then(([buildingRows, customerRows]) => {
        if (cancelled) return;
        setBuildings(buildingRows);
        setCustomers(customerRows);
        setLoadError("");
        setLoading(false);
      })
      .catch((err) => {
        if (cancelled) return;
        setLoadError(getApiError(err));
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // WAAR pre-selects itself when there is exactly one answer. Done as
  // an effect-free derivation: the select's VALUE falls back to the
  // only option, so no state write is needed until the user changes it.
  const effectiveBuilding: number | "" =
    building !== "" ? building : buildings.length === 1 ? buildings[0].id : "";

  /** The customer this melding belongs to — derived, never asked.
   *  The building's own customer link decides; a single-customer
   *  account short-circuits. */
  const derivedCustomer = useMemo(() => {
    if (customers.length === 1) return customers[0];
    if (effectiveBuilding === "") return null;
    return (
      customers.find(
        (row) =>
          row.building === effectiveBuilding ||
          row.linked_building_ids?.includes(Number(effectiveBuilding)),
      ) ?? null
    );
  }, [customers, effectiveBuilding]);

  function onPickFiles(picked: FileList | null) {
    if (!picked) return;
    const next = [...files];
    let rejected = false;
    for (const file of Array.from(picked)) {
      if (file.size > MAX_ATTACHMENT_BYTES) {
        rejected = true;
        continue;
      }
      next.push(file);
    }
    setFiles(next);
    setFileError(rejected ? t("melding_flow.photo_too_large") : "");
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  async function submit() {
    if (submitting) return;
    const text = description.trim();
    if (effectiveBuilding === "" || !text || !derivedCustomer) {
      setSubmitError(t("melding_flow.validation_incomplete"));
      return;
    }
    setSubmitting(true);
    setSubmitError("");
    try {
      const response = await api.post<{ id: number }>("/tickets/", {
        title: titleFrom(text),
        description: text,
        room_label: "",
        priority: urgent ? "URGENT" : "NORMAL",
        building: Number(effectiveBuilding),
        customer: derivedCustomer.id,
        customer_wanted_date: null,
      });
      const newId = response.data.id;
      let failed = false;
      for (const file of files) {
        const data = new FormData();
        data.append("file", file);
        try {
          await api.post(`/tickets/${newId}/attachments/`, data, {
            headers: { "Content-Type": "multipart/form-data" },
          });
        } catch {
          failed = true;
        }
      }
      setAttachmentWarning(failed);
      setCreatedId(newId);
    } catch (err) {
      setSubmitError(getApiError(err));
    } finally {
      setSubmitting(false);
    }
  }

  if (createdId !== null) {
    // §D.5.1 — the confirmation: what happens next, in phase words.
    return (
      <div data-testid="melding-created">
        <PageHeader
          eyebrow={t("melding_flow.eyebrow")}
          title={t("melding_flow.done_title")}
        />
        <section className="card" style={{ padding: 20, maxWidth: 640 }}>
          <p style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <CheckCircle2 size={18} strokeWidth={2} />
            {t("melding_flow.done_lead")}
          </p>
          <ol className="muted" style={{ paddingLeft: 20, lineHeight: 1.9 }}>
            <li>{t("melding_flow.done_step_received")}</li>
            <li>{t("melding_flow.done_step_planned")}</li>
            <li>{t("melding_flow.done_step_done")}</li>
          </ol>
          {attachmentWarning && (
            <p className="alert-error" role="alert">
              {t("melding_flow.photo_partial")}
            </p>
          )}
          <div style={{ display: "flex", gap: 10, marginTop: 12 }}>
            <Link
              to={`/tickets/${createdId}`}
              className="btn btn-primary btn-sm"
              data-testid="melding-created-open"
            >
              {t("melding_flow.done_open")}
            </Link>
            <Link to="/my/meldingen" className="btn btn-ghost btn-sm">
              {t("melding_flow.done_list")}
            </Link>
          </div>
        </section>
      </div>
    );
  }

  return (
    <div data-testid="melding-create-page">
      <PageHeader
        eyebrow={t("melding_flow.eyebrow")}
        title={t("melding_flow.title")}
        subtitle={t("melding_flow.subtitle")}
      />

      {loadError && (
        <div className="alert-error" role="alert" style={{ marginBottom: 16 }}>
          {loadError}
        </div>
      )}

      <form
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
        className="card"
        style={{ padding: 20, maxWidth: 640 }}
      >
        {/* WAAR */}
        <div className="field" style={{ marginBottom: 18 }}>
          <label className="field-label" htmlFor="melding-building">
            <MapPin size={14} strokeWidth={2} /> {t("melding_flow.q_where")}
          </label>
          {buildings.length === 1 ? (
            <p data-testid="melding-building-fixed" style={{ margin: 0 }}>
              {buildings[0].name}
            </p>
          ) : (
            <select
              id="melding-building"
              className="field-input"
              value={effectiveBuilding}
              onChange={(event) =>
                setBuilding(event.target.value ? Number(event.target.value) : "")
              }
              required
              data-testid="melding-building"
            >
              <option value="">{t("melding_flow.q_where_placeholder")}</option>
              {buildings.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.name}
                </option>
              ))}
            </select>
          )}
        </div>

        {/* WAT IS ER AAN DE HAND — the one description */}
        <div className="field" style={{ marginBottom: 18 }}>
          <label className="field-label" htmlFor="melding-description">
            <Megaphone size={14} strokeWidth={2} /> {t("melding_flow.q_what")}
          </label>
          <textarea
            id="melding-description"
            className="field-input"
            rows={5}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder={t("melding_flow.q_what_placeholder")}
            required
            data-testid="melding-description"
          />
        </div>

        {/* FOTO (optional) */}
        <div className="field" style={{ marginBottom: 18 }}>
          <label className="field-label" htmlFor="melding-photos">
            <Camera size={14} strokeWidth={2} /> {t("melding_flow.q_photo")}
          </label>
          <input
            id="melding-photos"
            ref={fileInputRef}
            type="file"
            accept="image/*"
            multiple
            className="field-input"
            onChange={(event) => onPickFiles(event.target.files)}
            data-testid="melding-photos"
          />
          {files.length > 0 && (
            <p className="muted small" style={{ marginTop: 6 }}>
              {t("melding_flow.photo_count", { count: files.length })}
            </p>
          )}
          {fileError && (
            <p className="alert-error" role="alert">
              {fileError}
            </p>
          )}
        </div>

        {/* Urgentie: Normaal default, one tap for Spoed. */}
        <label
          className="field"
          style={{
            display: "flex",
            flexDirection: "row",
            alignItems: "center",
            gap: 10,
            marginBottom: 18,
          }}
        >
          <input
            type="checkbox"
            checked={urgent}
            onChange={(event) => setUrgent(event.target.checked)}
            data-testid="melding-urgent"
          />
          <Siren size={14} strokeWidth={2} />
          <span>{t("melding_flow.q_urgent")}</span>
        </label>
        {urgent && (
          <p className="muted small" style={{ marginTop: -10, marginBottom: 16 }}>
            {t("melding_flow.q_urgent_helper")}
          </p>
        )}

        {submitError && (
          <div className="alert-error" role="alert" style={{ marginBottom: 12 }}>
            {submitError}
          </div>
        )}

        <button
          type="submit"
          className="btn btn-primary"
          disabled={submitting || loading}
          data-testid="melding-submit"
        >
          {submitting ? t("melding_flow.submitting") : t("melding_flow.submit")}
        </button>
      </form>
    </div>
  );
}
