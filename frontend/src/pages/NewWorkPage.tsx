/**
 * W11 — ONE DOOR.
 *
 * There were five: /tickets/new, /extra-work/new, Request a quote,
 * Recurring work, and Convert to extra work. Every one of them made a
 * person name the RECORD TYPE before they had said what happened, which
 * is backwards — you find out whether something is chargeable during the
 * conversation, not before it.
 *
 * So this page asks about the WORK and picks the record itself:
 *
 *     What is this about?      something is wrong / work needs doing
 *     Does it happen again?    once / it repeats
 *     Who pays for it?         the agreement / extra, order it
 *                              / extra, ask the price first
 *
 * Nothing here is new behaviour. Each answer lands on a route that
 * already existed, with the form it already had, creating exactly what
 * it already created. The specialised routes are untouched and stay
 * linked in the sidebar for people who already know which one they want.
 *
 * ## IT ONLY ASKS A QUESTION WHOSE ANSWERS DIFFER
 *
 * Extra work is closed to STAFF and recurring work is closed to STAFF
 * and customers, so for some roles two of the three questions have one
 * possible outcome. A question with one answer is a page asking
 * somebody to confirm what it already decided, so it is not shown — and
 * when every path leads to the same form, the door does not open at all
 * and the person goes straight there. A STAFF user pressing New sees the
 * ticket form, not an interview.
 *
 * ## A PROBLEM IS NEVER ASKED THE OTHER TWO
 *
 * "Something is wrong" is a report. Nobody schedules a complaint every
 * Tuesday, and whether the fix turns out to be chargeable is discovered
 * after somebody looks at it — which is what Convert to extra work on
 * the ticket is for. So that branch answers one question and stops.
 *
 * Convert stays where it is and is deliberately NOT a choice here: it
 * acts on a ticket that already exists, so it cannot be a way to start.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  BadgeEuro,
  CalendarClock,
  ClipboardList,
  FileText,
  Repeat,
} from "lucide-react";

import { useAuth } from "../auth/AuthContext";
import { canAccessExtraWork, canAccessPlannedWork } from "../auth/permissions";

type About = "problem" | "request";
type Repeats = "once" | "repeats";

interface Answer {
  key: string;
  label: string;
  description: string;
  icon: typeof FileText;
  onPick: () => void;
}

export function NewWorkPage() {
  const { t } = useTranslation(["common"]);
  const navigate = useNavigate();
  const { me } = useAuth();

  const mayExtraWork = canAccessExtraWork(me?.role);
  const mayRecur = canAccessPlannedWork(me?.role);

  const [about, setAbout] = useState<About | null>(null);
  const [repeats, setRepeats] = useState<Repeats | null>(null);

  /** Every destination already exists. W13 — the ticket form's field is
   *  now a CATEGORY from the company's catalog, so this hands over the
   *  category SLUG rather than the superseded `type` enum. A slug and
   *  not an id because the id differs per company and the slug does
   *  not. Pre-filled from what was just asked, so the form does not ask
   *  it a second time. */
  const goTicket = (categorySlug: "melden" | "verzoek") =>
    navigate(`/tickets/new?category=${categorySlug}`);
  const goRecurring = () => navigate("/planned-work/new");
  const goOrder = () => navigate("/extra-work/new");
  const goQuote = () => navigate("/extra-work/request-quote");

  // When neither of the branching questions can branch, "New" has one
  // possible outcome and asking is theatre. `<Navigate>` rather than
  // calling `navigate()` here: a redirect is what this render RETURNS,
  // not something it does on the side.
  if (!mayExtraWork && !mayRecur) {
    return <Navigate to="/tickets/new?category=melden" replace />;
  }

  const aboutAnswers: Answer[] = [
    {
      key: "problem",
      label: t("new_work.about_problem"),
      description: t("new_work.about_problem_desc"),
      icon: AlertTriangle,
      onPick: () => goTicket("melden"),
    },
    {
      key: "request",
      label: t("new_work.about_request"),
      description: t("new_work.about_request_desc"),
      icon: ClipboardList,
      onPick: () => {
        setAbout("request");
        // Recurring is the only thing the repeat question decides. With
        // it closed to this role there is nothing to ask.
        if (!mayRecur) setRepeats("once");
      },
    },
  ];

  const repeatAnswers: Answer[] = [
    {
      key: "once",
      label: t("new_work.repeat_once"),
      description: t("new_work.repeat_once_desc"),
      icon: FileText,
      onPick: () => setRepeats("once"),
    },
    {
      key: "repeats",
      label: t("new_work.repeat_repeats"),
      description: t("new_work.repeat_repeats_desc"),
      icon: Repeat,
      onPick: goRecurring,
    },
  ];

  const paysAnswers: Answer[] = [
    {
      key: "agreement",
      label: t("new_work.pays_agreement"),
      description: t("new_work.pays_agreement_desc"),
      icon: FileText,
      onPick: () => goTicket("verzoek"),
    },
    {
      key: "order",
      label: t("new_work.pays_order"),
      description: t("new_work.pays_order_desc"),
      icon: CalendarClock,
      onPick: goOrder,
    },
    {
      key: "quote",
      label: t("new_work.pays_quote"),
      description: t("new_work.pays_quote_desc"),
      icon: BadgeEuro,
      onPick: goQuote,
    },
  ];

  /** The question on screen now, and the ones already answered above
   *  it. Only one is ever open. */
  const answered: { key: string; question: string; answer: string;
                    onChange: () => void }[] = [];
  let question = t("new_work.q_about");
  let answers = aboutAnswers;

  if (about === "request") {
    answered.push({
      key: "about",
      question: t("new_work.q_about"),
      answer: t("new_work.about_request"),
      onChange: () => {
        setAbout(null);
        setRepeats(null);
      },
    });
    if (repeats === null) {
      question = t("new_work.q_repeat");
      answers = repeatAnswers;
    } else {
      if (mayRecur) {
        answered.push({
          key: "repeat",
          question: t("new_work.q_repeat"),
          answer: t("new_work.repeat_once"),
          onChange: () => setRepeats(null),
        });
      }
      question = t("new_work.q_pays");
      answers = paysAnswers;
    }
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="eyebrow">{t("new_work.eyebrow")}</div>
          <h2 className="page-title">{t("new_work.title")}</h2>
          <p className="page-sub">{t("new_work.subtitle")}</p>
        </div>
      </div>

      {/* W-P4 §2 — THE SHAPE, NOT THE WORDS.
          Measured at 1366: the column is 1054 wide and this card was
          720, so a third of the page was blank and each option was a
          wide thin strip 670x71. Nothing here is a new component or a
          new style: the same card, the same icon chip, the same label
          and description classes, laid out so an option looks like an
          option. The rules are inline rather than in `index.css`
          because that file is being changed on another branch right
          now; fold them into `.new-work-card` / `.new-work-answers` /
          `.new-work-answer` when it is free. */}
      <div
        className="card new-work-card"
        style={{ maxWidth: 1000 }}
        data-testid="new-work"
      >
        {answered.map((step) => (
          <div className="new-work-answered" key={step.key}>
            <span className="new-work-answered-q">{step.question}</span>
            <span className="new-work-answered-a">{step.answer}</span>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={step.onChange}
              data-testid={`new-work-change-${step.key}`}
            >
              {t("new_work.change")}
            </button>
          </div>
        ))}

        <h3 className="new-work-question" data-testid="new-work-question">
          {question}
        </h3>
        {/* `auto-fit` and NOT a written-down column count: the two-answer
            questions fill the row as two, the three-answer one fills it
            as three, and a narrow window drops to one without a media
            query. There is no number here to keep in step with the
            number of options.
            `min(280px, 100%)` and not a bare `280px`: a bare minimum
            still builds a 280px track when the column is NARROWER than
            280, which measured as a card that overflowed its own box at
            a 320px viewport. Capping the minimum at the column width
            lets the single column shrink instead. */}
        <div
          className="new-work-answers"
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(min(280px, 100%), 1fr))",
            gap: 14,
          }}
        >
          {answers.map((answer) => {
            const Icon = answer.icon;
            return (
              <button
                type="button"
                key={answer.key}
                className="new-work-answer"
                onClick={answer.onPick}
                /* Icon above the words instead of beside them. Side by
                   side, a card this wide is mostly empty to the right of
                   the description; stacked, the option gets its size
                   back and the row still reads left to right. */
                style={{
                  flexDirection: "column",
                  alignItems: "stretch",
                  padding: "18px 18px 20px",
                }}
                data-testid={`new-work-answer-${answer.key}`}
              >
                <span
                  className="new-work-answer-icon"
                  style={{ width: 40, height: 40 }}
                >
                  <Icon size={20} strokeWidth={2} aria-hidden="true" />
                </span>
                <span className="new-work-answer-text">
                  <span className="new-work-answer-label">{answer.label}</span>
                  <span className="new-work-answer-desc">
                    {answer.description}
                  </span>
                </span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
