/**
 * FE-2 (Addendum D §D.5.2) — the customer's guided meerwerk flow.
 *
 * One decision per step: WAAR (pre-selected when there is exactly one
 * building) → WAT (the services with THEIR agreed prices, plus the
 * "iets anders" free-text lines) → WANNEER (one date wish) →
 * BEVESTIGEN, where the SYSTEM states what happens next, derived from
 * the cart by the server's own preview (SoT §5 rules): all agreed
 * prices → scheduled right away; any custom line → a price comes
 * first. The auto-start choice appears only when the server's
 * `allowed_intents` offers it (SoT §5.3 role rule — never re-derived
 * client-side).
 *
 * Gefactureerd aan / afdeling / werktype / categorie / urgentie are
 * NOT asked (§D.5.2's recorded decision): building-level defaults go
 * to the server, the provider corrects later. Submission goes through
 * the EXISTING create endpoint; title and description are derived from
 * the cart so the server contract is untouched.
 *
 * FE-5 — the cart pieces (picker, custom lines, confirm list, outcome
 * sentence) moved to `components/meerwerk/` and are the same pieces the
 * provider's create page renders.
 */
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  Calendar,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  MapPin,
  Receipt,
} from "lucide-react";

import {
  listAllBuildings,
  listAllCustomers,
  listCustomerCustomPrices,
  listCustomerPrices,
} from "../../api/admin";
import { getApiError } from "../../api/client";
import {
  createExtraWork,
  getExtraWorkPreview,
} from "../../api/extraWork";
import type {
  Building,
  Customer,
  CustomerCustomPrice,
  CustomerServicePrice,
  ExtraWorkPreviewResponse,
  ExtraWorkRequestDetail,
} from "../../api/types";
import { PageHeader } from "../../components/PageHeader";
import {
  cartLineItemsPayload,
  derivedDescription,
  derivedTitle,
  otherLineFromText,
  otherLinesToCart,
  type MeerwerkCartLine,
  type OtherLineDraft,
} from "../../components/meerwerk/cart";
import { CartSummaryList } from "../../components/meerwerk/CartSummaryList";
import { MeerwerkOutcome } from "../../components/meerwerk/MeerwerkOutcome";
import {
  OtherLinesEditor,
  UnaddedOtherLineNotice,
} from "../../components/meerwerk/OtherLinesEditor";
import { PricedServicePicker } from "../../components/meerwerk/PricedServicePicker";

type Step = 0 | 1 | 2 | 3;

const STEP_KEYS = ["where", "what", "when", "confirm"] as const;

export function MeerwerkFlowPage() {
  const { t } = useTranslation(["common", "extra_work"]);

  const [buildings, setBuildings] = useState<Building[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [prices, setPrices] = useState<CustomerServicePrice[]>([]);
  const [customPrices, setCustomPrices] = useState<CustomerCustomPrice[]>([]);
  const [loadError, setLoadError] = useState("");

  const [step, setStep] = useState<Step>(0);
  const [building, setBuilding] = useState<number | "">("");
  const [cart, setCart] = useState<MeerwerkCartLine[]>([]);
  /** FE-4 (Addendum D §D.12 item 6) — "Iets anders" is a real cart line,
   *  and there can be several. P-9 C1: a line exists once Add was
   *  pressed; the box's own text is asked about before moving on. */
  const [others, setOthers] = useState<OtherLineDraft[]>([]);
  const [otherDraft, setOtherDraft] = useState("");
  const [unaddedAsk, setUnaddedAsk] = useState(false);
  const [wishDate, setWishDate] = useState("");
  // P-11 A3 — the hard date, asked under the wish. Optional.
  const [deadline, setDeadline] = useState("");
  const [autoStart, setAutoStart] = useState(false);

  const [preview, setPreview] = useState<ExtraWorkPreviewResponse | null>(null);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const [created, setCreated] = useState<ExtraWorkRequestDetail | null>(null);

  const effectiveBuilding: number | "" =
    building !== "" ? building : buildings.length === 1 ? buildings[0].id : "";

  const customer = useMemo(() => {
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

  useEffect(() => {
    let cancelled = false;
    Promise.all([listAllBuildings(), listAllCustomers()])
      .then(([buildingRows, customerRows]) => {
        if (cancelled) return;
        setBuildings(buildingRows);
        setCustomers(customerRows);
      })
      .catch((err) => {
        if (!cancelled) setLoadError(getApiError(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // THEIR agreed prices — the SoT §5.7 rule is the server's (these two
  // endpoints only answer customer-specific prices); the flow simply
  // never asks for anything else.
  useEffect(() => {
    if (!customer) return;
    let cancelled = false;
    Promise.all([
      listCustomerPrices(customer.id),
      // Custom prices are readable only by some customer roles (the
      // endpoint 403s the rest); a refusal simply means none to offer.
      listCustomerCustomPrices(customer.id).catch(
        () => [] as CustomerCustomPrice[],
      ),
    ])
      .then(([priceRows, customRows]) => {
        if (cancelled) return;
        setPrices(priceRows.filter((row) => row.is_active));
        setCustomPrices(customRows.filter((row) => row.is_active));
      })
      .catch((err) => {
        if (!cancelled) setLoadError(getApiError(err));
      });
    return () => {
      cancelled = true;
    };
  }, [customer]);

  const cartWithOther = useMemo(
    () => [...cart, ...otherLinesToCart(others)],
    [cart, others],
  );

  function addOther() {
    const text = otherDraft.trim();
    if (!text) return;
    setOthers((prev) => [...prev, otherLineFromText(text, prev.length + 1)]);
    setOtherDraft("");
    setUnaddedAsk(false);
  }
  function removeOther(key: string) {
    setOthers((prev) => prev.filter((row) => row.key !== key));
  }

  /** The confirm step's statement comes from the SERVER's preview —
   *  the same classifier the create endpoint runs (§D.5.2: the system
   *  STATES what happens; nothing is inferred here). Fired from the
   *  "next" click that enters the confirm step, so the answer always
   *  describes the cart the reader is looking at. */
  async function loadPreview() {
    if (!customer || effectiveBuilding === "" || cartWithOther.length === 0) {
      return;
    }
    setPreviewBusy(true);
    setPreview(null);
    try {
      const data = await getExtraWorkPreview({
        building: Number(effectiveBuilding),
        customer: customer.id,
        preferred_date: wishDate || undefined,
        line_items: cartLineItemsPayload(cartWithOther),
      });
      setPreview(data);
    } catch (err) {
      setSubmitError(getApiError(err));
    } finally {
      setPreviewBusy(false);
    }
  }

  function toggleLine(line: MeerwerkCartLine) {
    setCart((prev) =>
      prev.some((row) => row.key === line.key)
        ? prev.filter((row) => row.key !== line.key)
        : [...prev, line],
    );
  }

  function setQuantity(key: string, quantity: number) {
    setCart((prev) =>
      prev.map((row) =>
        row.key === key ? { ...row, quantity: Math.max(1, quantity) } : row,
      ),
    );
  }

  async function submit() {
    if (submitting || !customer || effectiveBuilding === "") return;
    setSubmitting(true);
    setSubmitError("");
    try {
      const detail = await createExtraWork({
        building: Number(effectiveBuilding),
        customer: customer.id,
        title: derivedTitle(cartWithOther),
        description: derivedDescription(
          cartWithOther,
          t("meerwerk_flow.other_prefix"),
        ),
        preferred_date: wishDate || null,
        // P-11 A3 — the hard date rides along when one was given.
        deadline: deadline || null,
        billed_to: null,
        // §D.5.2 — urgentie is not asked; the server default stands.
        urgency: "NORMAL",
        ...(autoStart ? { request_intent: "AUTO_START_AFTER_PRICING" } : {}),
        line_items: cartLineItemsPayload(cartWithOther),
      });
      setCreated(detail);
    } catch (err) {
      setSubmitError(getApiError(err));
    } finally {
      setSubmitting(false);
    }
  }

  const stepValid =
    step === 0
      ? effectiveBuilding !== "" && customer !== null
      : step === 1
        ? cartWithOther.length > 0 || otherDraft.trim() !== ""
        : true;

  const autoStartOffered =
    preview?.allowed_intents?.includes("AUTO_START_AFTER_PRICING") ?? false;
  const allAgreed = preview?.cart?.all_agreed ?? false;

  if (created) {
    const instant = created.routing_decision === "INSTANT";
    return (
      <div data-testid="meerwerk-created">
        <PageHeader
          eyebrow={t("meerwerk_flow.eyebrow")}
          title={t("meerwerk_flow.done_title")}
        />
        <section className="card" style={{ padding: 20, maxWidth: 640 }}>
          <p style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <CheckCircle2 size={18} strokeWidth={2} />
            {instant
              ? t("meerwerk_flow.done_instant")
              : autoStart
                ? t("meerwerk_flow.done_auto_start")
                : t("meerwerk_flow.done_quote")}
          </p>
          <div style={{ display: "flex", gap: 10, marginTop: 12 }}>
            <Link
              to={`/extra-work/${created.id}`}
              className="btn btn-primary btn-sm"
              data-testid="meerwerk-created-open"
            >
              {t("meerwerk_flow.done_open")}
            </Link>
            <Link to="/extra-work" className="btn btn-ghost btn-sm">
              {t("meerwerk_flow.done_list")}
            </Link>
          </div>
        </section>
      </div>
    );
  }

  return (
    <div data-testid="meerwerk-flow-page">
      <PageHeader
        eyebrow={t("meerwerk_flow.eyebrow")}
        title={t("meerwerk_flow.title")}
        subtitle={t(`meerwerk_flow.step_${STEP_KEYS[step]}_sub`)}
      />

      {/* The stepper — where the reader stands, four words. */}
      <ol className="meerwerk-steps" data-testid="meerwerk-steps">
        {STEP_KEYS.map((key, index) => (
          <li
            key={key}
            className={
              index === step
                ? "meerwerk-step active"
                : index < step
                  ? "meerwerk-step done"
                  : "meerwerk-step"
            }
          >
            {t(`meerwerk_flow.step_${key}`)}
          </li>
        ))}
      </ol>

      {loadError && (
        <div className="alert-error" role="alert" style={{ marginBottom: 16 }}>
          {loadError}
        </div>
      )}

      <section className="card" style={{ padding: 20, maxWidth: 720 }}>
        {step === 0 && (
          <div className="field">
            <label className="field-label" htmlFor="meerwerk-building">
              <MapPin size={14} strokeWidth={2} /> {t("meerwerk_flow.q_where")}
            </label>
            {buildings.length === 1 ? (
              <p data-testid="meerwerk-building-fixed" style={{ margin: 0 }}>
                {buildings[0].name}
              </p>
            ) : (
              <select
                id="meerwerk-building"
                className="field-input"
                value={effectiveBuilding}
                onChange={(event) =>
                  setBuilding(
                    event.target.value ? Number(event.target.value) : "",
                  )
                }
                data-testid="meerwerk-building"
              >
                <option value="">
                  {t("meerwerk_flow.q_where_placeholder")}
                </option>
                {buildings.map((row) => (
                  <option key={row.id} value={row.id}>
                    {row.name}
                  </option>
                ))}
              </select>
            )}
          </div>
        )}

        {step === 1 && (
          <>
            <div className="field-label" style={{ marginBottom: 8 }}>
              <Receipt size={14} strokeWidth={2} /> {t("meerwerk_flow.q_what")}
            </div>
            <PricedServicePicker
              prices={prices}
              customPrices={customPrices}
              cart={cart}
              onToggle={toggleLine}
              onQuantity={setQuantity}
              emptyLabel={t("meerwerk_flow.no_agreed_prices")}
              testIdPrefix="meerwerk"
            />
            <OtherLinesEditor
              others={others}
              draft={otherDraft}
              onDraftChange={(text) => {
                setOtherDraft(text);
                setUnaddedAsk(false);
              }}
              onAdd={addOther}
              onRemove={removeOther}
              testIdPrefix="meerwerk"
            />
            {unaddedAsk && otherDraft.trim() !== "" && (
              <UnaddedOtherLineNotice
                text={otherDraft.trim()}
                onAddIt={addOther}
                onIgnore={() => {
                  setOtherDraft("");
                  setUnaddedAsk(false);
                }}
                testIdPrefix="meerwerk"
              />
            )}
          </>
        )}

        {step === 2 && (
          <div className="field">
            <label className="field-label" htmlFor="meerwerk-date">
              <Calendar size={14} strokeWidth={2} /> {t("meerwerk_flow.q_when")}
            </label>
            <input
              id="meerwerk-date"
              type="date"
              className="field-input"
              value={wishDate}
              onChange={(event) => setWishDate(event.target.value)}
              data-testid="meerwerk-date"
            />
            <p className="muted small" style={{ marginTop: 6 }}>
              {t("meerwerk_flow.q_when_helper")}
            </p>
            {/* P-11 A3 — the deadline, under the wish, optional. */}
            <label
              className="field-label"
              htmlFor="meerwerk-deadline"
              style={{ marginTop: 12 }}
            >
              <Calendar size={14} strokeWidth={2} />{" "}
              {t("extra_work:create.field_deadline")}
            </label>
            <input
              id="meerwerk-deadline"
              type="date"
              className="field-input"
              value={deadline}
              onChange={(event) => setDeadline(event.target.value)}
              data-testid="meerwerk-deadline"
            />
            <p className="muted small" style={{ marginTop: 6 }}>
              {t("extra_work:create.deadline_hint")}
            </p>
          </div>
        )}

        {step === 3 && (
          <div data-testid="meerwerk-confirm">
            <div className="section-head-title" style={{ marginBottom: 8 }}>
              {t("meerwerk_flow.confirm_title")}
            </div>
            <CartSummaryList lines={cartWithOther} testIdPrefix="meerwerk" />
            <p className="muted small">
              {t("meerwerk_flow.confirm_where_when", {
                building:
                  buildings.find((row) => row.id === effectiveBuilding)?.name ??
                  "",
                date: wishDate || t("meerwerk_flow.no_date_wish"),
              })}
            </p>
            {previewBusy ? (
              <div className="loading-bar">
                <div className="loading-bar-fill" />
              </div>
            ) : (
              preview && (
                <MeerwerkOutcome
                  audience="customer"
                  kind={
                    allAgreed
                      ? "instant"
                      : autoStart && autoStartOffered
                        ? "auto_start"
                        : "quote"
                  }
                />
              )
            )}
            {/* SoT §5.3 — offered only when the server's allowed_intents
                says this actor may choose it. */}
            {autoStartOffered && (
              <label
                style={{
                  display: "flex",
                  gap: 10,
                  alignItems: "center",
                  marginTop: 8,
                }}
              >
                <input
                  type="checkbox"
                  checked={autoStart}
                  onChange={(event) => setAutoStart(event.target.checked)}
                  data-testid="meerwerk-auto-start"
                />
                <span>{t("meerwerk_flow.auto_start_label")}</span>
              </label>
            )}
            {submitError && (
              <div className="alert-error" role="alert" style={{ marginTop: 10 }}>
                {submitError}
              </div>
            )}
          </div>
        )}

        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            marginTop: 20,
          }}
        >
          {step > 0 ? (
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => setStep((step - 1) as Step)}
              data-testid="meerwerk-back"
            >
              <ChevronLeft size={14} strokeWidth={2} />
              {t("meerwerk_flow.back")}
            </button>
          ) : (
            <span />
          )}
          {step < 3 ? (
            <button
              type="button"
              className="btn btn-primary btn-sm"
              disabled={!stepValid}
              onClick={() => {
                // P-9 C1 — the box still holds text: ask before moving on.
                if (step === 1 && otherDraft.trim() !== "") {
                  setUnaddedAsk(true);
                  return;
                }
                const next = (step + 1) as Step;
                setStep(next);
                if (next === 3) void loadPreview();
              }}
              data-testid="meerwerk-next"
            >
              {t("meerwerk_flow.next")}
              <ChevronRight size={14} strokeWidth={2} />
            </button>
          ) : (
            <button
              type="button"
              className="btn btn-primary"
              disabled={submitting || previewBusy || !preview}
              onClick={() => void submit()}
              data-testid="meerwerk-submit"
            >
              {submitting
                ? t("meerwerk_flow.submitting")
                : t("meerwerk_flow.submit")}
            </button>
          )}
        </div>
      </section>
    </div>
  );
}
