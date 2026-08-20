// W4-P — the GLOBAL half of the photo-upload permission, on the
// permissions screen.
//
// The owner's ask: "sometimes the provider or the manager should be able
// to give permissions to the staff to not need this. for example give
// pre permission to ahmet and from then his uploaded photos are in the
// pool. ... permission page is for all of the tickets. and the tickets
// assignment is that spesific ticket. and this should be clearly
// stated."
//
// So the card's whole job is to be UNMISTAKABLY the every-ticket one. It
// says so in its subtitle, it says so again beside the control, and it
// names the per-ticket setting as the thing that overrides it — because
// two switches that look alike and reach differently is how an operator
// releases a photo they meant to keep internal.
//
// THREE STATES, not two, and they are deliberately not a toggle:
//   Granted   — this person's uploads land customer-visible everywhere.
//   Refused   — they stay internal everywhere, beating the per-work
//               setting. The state that exists so a trainee's photos can
//               be held back on a work whose customer sees everything.
//   Not set   — the default. Nothing decided; each ticket falls through
//               to its own setting and, failing that, to internal.
// A two-state toggle cannot express "refused" and "not set" separately,
// and collapsing them would silently turn every unset person into a
// refusal the moment somebody opened a work up.
//
// Rendered only for SUPER_ADMIN / COMPANY_ADMIN (the roles the backend
// admits) and never for the viewer's own row: granting is privileged and
// never self-service, which the server enforces with a 403 and this card
// states rather than discovers.
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../api/client";
import {
  getStandingUploadVisibility,
  setStandingUploadVisibility,
} from "../../api/uploadVisibility";
import { useAuth } from "../../auth/AuthContext";

type Decision = "GRANTED" | "REFUSED" | "UNSET";

const DECISION_TO_VALUE: Record<Decision, boolean | null> = {
  GRANTED: true,
  REFUSED: false,
  UNSET: null,
};

// ONE ordered constant that every consumer in this file iterates — the
// Sprint 130 lesson. Deliberately not exported: `react-refresh`'s
// only-export-components rule counts a non-component export from a
// component module as a violation, and the ESLint baseline is exactly 44.
// If a second file ever needs this order, it moves to its own module
// rather than growing a copy.
const UPLOAD_VISIBILITY_DECISIONS: readonly Decision[] = [
  "GRANTED",
  "REFUSED",
  "UNSET",
] as const;

function toDecision(value: boolean | null): Decision {
  if (value === null) return "UNSET";
  return value ? "GRANTED" : "REFUSED";
}

export function UploadVisibilityCard({
  userId,
  userFullName,
}: {
  userId: number;
  userFullName: string;
}) {
  const { t } = useTranslation();
  const { me } = useAuth();

  const [decision, setDecision] = useState<Decision | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  const [fetchFailed, setFetchFailed] = useState(false);

  // Whether this viewer's ROLE may read the endpoint is knowable during
  // render, so it is derived and not stored. Putting it in state would
  // mean a `setState` in the effect body, which the platform rule
  // forbids (cascading renders) and ESLint enforces. Only the fetch
  // OUTCOME — which is genuinely external — lives in state, and it is
  // set from a promise callback, not synchronously.
  const roleMayRead =
    me?.role === "SUPER_ADMIN" || me?.role === "COMPANY_ADMIN";
  const canEdit = roleMayRead && me?.id !== userId;

  useEffect(() => {
    if (!roleMayRead) return;
    let cancelled = false;
    getStandingUploadVisibility(userId)
      .then((state) => {
        if (cancelled) return;
        setDecision(toDecision(state.uploads_customer_visible));
      })
      .catch(() => {
        // A viewer who cannot read the endpoint gets no card at all,
        // the defensive shape the other read-only cards on this page
        // use: a 403 must not break the page.
        if (!cancelled) setFetchFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [userId, roleMayRead]);

  async function choose(next: Decision) {
    if (saving || next === decision) return;
    setSaving(true);
    setError("");
    setSaved(false);
    try {
      const state = await setStandingUploadVisibility(
        userId,
        DECISION_TO_VALUE[next],
      );
      setDecision(toDecision(state.uploads_customer_visible));
      setSaved(true);
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setSaving(false);
    }
  }

  if (!roleMayRead || fetchFailed || decision === null) return null;

  return (
    <section
      className="card"
      data-testid="user-detail-upload-visibility-card"
      data-decision={decision}
      style={{ padding: "20px 22px", marginBottom: 16 }}
    >
      <div className="section-head" style={{ marginBottom: 8 }}>
        <div>
          <div className="section-head-title">
            {t("user_detail.upload_visibility.title")}
          </div>
          <div
            className="section-head-sub"
            data-testid="user-detail-upload-visibility-scope"
          >
            {t("user_detail.upload_visibility.scope", {
              name: userFullName,
            })}
          </div>
        </div>
      </div>

      <div
        className="form-row"
        role="radiogroup"
        aria-label={t("user_detail.upload_visibility.title")}
        style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 4 }}
      >
        {UPLOAD_VISIBILITY_DECISIONS.map((option) => (
          <button
            key={option}
            type="button"
            role="radio"
            aria-checked={decision === option}
            disabled={!canEdit || saving}
            className={
              decision === option ? "btn btn-primary" : "btn btn-secondary"
            }
            data-testid={`user-detail-upload-visibility-${option.toLowerCase()}`}
            onClick={() => void choose(option)}
          >
            {t(`user_detail.upload_visibility.option_${option.toLowerCase()}`)}
          </button>
        ))}
      </div>

      <p
        className="muted"
        data-testid="user-detail-upload-visibility-explainer"
        style={{ marginTop: 10, marginBottom: 0 }}
      >
        {t(`user_detail.upload_visibility.explain_${decision.toLowerCase()}`)}
      </p>
      <p
        className="muted"
        data-testid="user-detail-upload-visibility-precedence"
        style={{ marginTop: 6, marginBottom: 0 }}
      >
        {t("user_detail.upload_visibility.precedence")}
      </p>

      {!canEdit && (
        <p
          className="muted"
          data-testid="user-detail-upload-visibility-readonly"
          style={{ marginTop: 6, marginBottom: 0 }}
        >
          {t(
            me?.id === userId
              ? "user_detail.upload_visibility.read_only_self"
              : "user_detail.upload_visibility.read_only",
          )}
        </p>
      )}
      {saved && (
        <p
          className="form-success"
          data-testid="user-detail-upload-visibility-saved"
        >
          {t("user_detail.upload_visibility.saved")}
        </p>
      )}
      {error && (
        <p
          className="form-error"
          data-testid="user-detail-upload-visibility-error"
        >
          {error}
        </p>
      )}
    </section>
  );
}
