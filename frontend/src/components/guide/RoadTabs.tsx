/**
 * P-12 §D.24 rule 3 — tabs are the steps of the road, in the order
 * things happen, numbered, each with its count. Two variants:
 *
 *   "tabs"     — the list page's tablist. Steps are Links (the tab is
 *                in the URL) or buttons; the active step is marked.
 *   "progress" — the read-only road on a detail page or a card: the
 *                current step marked, earlier steps done, later steps
 *                ahead. Nothing is clickable; counts are not shown.
 *
 * Pages pass their ONE exported ordered constant as `steps` (the
 * exhaustiveness rule — never a second local array) and build the
 * numbered eyebrow with `stepEyebrow`. The pure state derivation lives
 * in roadSteps.ts, vitest-pinned.
 */
import { Link } from "react-router-dom";

import { roadStepStates, stepEyebrow } from "./roadSteps";
import "./guide.css";

export interface RoadStep<K extends string = string> {
  key: K;
  /** The step word for the numbered eyebrow — "Finished work". */
  step: string;
  /** The tab's own name — "To invoice". */
  label: string;
  /** null renders "…" (still loading); undefined renders no count. */
  count?: number | null;
  /** Link target in "tabs" variant; falls back to onSelect. */
  to?: string;
}

export function RoadTabs<K extends string>({
  steps,
  activeKey,
  onSelect,
  variant = "tabs",
  ariaLabel,
  testIdPrefix,
}: {
  steps: readonly RoadStep<K>[];
  activeKey: K | null;
  onSelect?: (key: K) => void;
  variant?: "tabs" | "progress";
  ariaLabel: string;
  testIdPrefix: string;
}) {
  if (variant === "progress") {
    const states = roadStepStates(
      steps.map((s) => s.key),
      activeKey,
    );
    return (
      <ol className="guide-road guide-road-progress" aria-label={ariaLabel} data-testid={testIdPrefix}>
        {steps.map((step, i) => (
          <li
            key={step.key}
            className={`guide-step guide-step-${states[i]}`}
            aria-current={states[i] === "current" ? "step" : undefined}
            data-testid={`${testIdPrefix}-${step.key}`}
            data-state={states[i]}
          >
            <span className="guide-step-no">{stepEyebrow(i, step.step)}</span>
            <span className="guide-step-nm">{step.label}</span>
          </li>
        ))}
      </ol>
    );
  }

  return (
    <div className="guide-road" role="tablist" aria-label={ariaLabel} data-testid={testIdPrefix}>
      {steps.map((step, i) => {
        const active = step.key === activeKey;
        const body = (
          <>
            <span className="guide-step-no">{stepEyebrow(i, step.step)}</span>
            <span className="guide-step-nm">
              {step.label}
              {step.count !== undefined && (
                <span
                  className="guide-step-n"
                  data-testid={`${testIdPrefix}-count-${step.key}`}
                >
                  {step.count === null ? "…" : step.count}
                </span>
              )}
            </span>
          </>
        );
        const className = `guide-step${active ? " guide-step-current" : ""}`;
        if (step.to) {
          return (
            <Link
              key={step.key}
              to={step.to}
              role="tab"
              aria-selected={active}
              className={className}
              data-testid={`${testIdPrefix}-${step.key}`}
            >
              {body}
            </Link>
          );
        }
        return (
          <button
            key={step.key}
            type="button"
            role="tab"
            aria-selected={active}
            className={className}
            onClick={() => onSelect?.(step.key)}
            data-testid={`${testIdPrefix}-${step.key}`}
          >
            {body}
          </button>
        );
      })}
    </div>
  );
}

/**
 * Rule 3's second half — the tab's first line teaches the step: what
 * it means, what the button does, what can still change. `money` is
 * the tab's one summary line (§D.22 rule 4), labelled with which set
 * it means.
 */
export function TeachHead({
  title,
  body,
  money,
  testId = "guide-teach",
}: {
  title: string;
  body: string;
  money?: { value: string; label: string };
  testId?: string;
}) {
  return (
    <div className="guide-teach" data-testid={testId}>
      <div className="guide-teach-words">
        <h2 className="guide-teach-title">{title}</h2>
        <p className="guide-teach-body">{body}</p>
      </div>
      {money && (
        <div className="guide-money" data-testid={`${testId}-money`}>
          <b>{money.value}</b>
          {money.label}
        </div>
      )}
    </div>
  );
}
