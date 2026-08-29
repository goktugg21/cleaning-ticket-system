import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import nlCommon from "./nl/common.json";
import nlLogin from "./nl/login.json";
import nlSettings from "./nl/settings.json";
import nlDashboard from "./nl/dashboard.json";
import nlTicketDetail from "./nl/ticket_detail.json";
import nlCreateTicket from "./nl/create_ticket.json";
import nlReports from "./nl/reports.json";
import nlExtraWork from "./nl/extra_work.json";
import nlPlannedWork from "./nl/planned_work.json";
import nlStaffSlots from "./nl/staff_slots.json";
import nlStaffCredentials from "./nl/staff_credentials.json";
// Sprint 160 — contracts gets its OWN namespace rather than another
// 2000 keys in common.json. A module-sized bundle is also the only
// thing that keeps two sprints working in parallel from conflicting
// on every line either of them adds.
import nlContracts from "./nl/contracts.json";
// Sprint 183 §1 — invoicing gets its own namespace. The Facturen page
// and the customer Facturatie section keep "common" as their DEFAULT
// (every existing bare key on those pages resolves there and must go
// on doing so — this app sets no fallbackNS), and reference the new
// strings explicitly as "invoices:...".
import nlInvoices from "./nl/invoices.json";
import enCommon from "./en/common.json";
import enLogin from "./en/login.json";
import enSettings from "./en/settings.json";
import enDashboard from "./en/dashboard.json";
import enTicketDetail from "./en/ticket_detail.json";
import enCreateTicket from "./en/create_ticket.json";
import enReports from "./en/reports.json";
import enExtraWork from "./en/extra_work.json";
import enPlannedWork from "./en/planned_work.json";
import enStaffSlots from "./en/staff_slots.json";
import enStaffCredentials from "./en/staff_credentials.json";
import enContracts from "./en/contracts.json";
import enInvoices from "./en/invoices.json";

// FE-4 (Addendum D §D.12 item 9) — the PRE-AUTH language follows the
// browser: an English browser opening the login page met a Dutch screen
// (the default was a hardcoded "nl"), which is the one way Dutch could
// reach an English session with every string in the app going through
// t(). Once the user is authenticated, useLanguageSync switches to
// me.language — the profile stays the authority; the browser only
// decides what the login page says. No localStorage cache, as before.
const browserLanguage =
  typeof navigator !== "undefined" &&
  (navigator.language || "").toLowerCase().startsWith("en")
    ? "en"
    : "nl";

i18n.use(initReactI18next).init({
  resources: {
    nl: {
      common: nlCommon,
      login: nlLogin,
      settings: nlSettings,
      dashboard: nlDashboard,
      ticket_detail: nlTicketDetail,
      create_ticket: nlCreateTicket,
      reports: nlReports,
      extra_work: nlExtraWork,
      planned_work: nlPlannedWork,
      staff_slots: nlStaffSlots,
      staff_credentials: nlStaffCredentials,
      contracts: nlContracts,
      invoices: nlInvoices,
    },
    en: {
      common: enCommon,
      login: enLogin,
      settings: enSettings,
      dashboard: enDashboard,
      ticket_detail: enTicketDetail,
      create_ticket: enCreateTicket,
      reports: enReports,
      extra_work: enExtraWork,
      planned_work: enPlannedWork,
      staff_slots: enStaffSlots,
      staff_credentials: enStaffCredentials,
      contracts: enContracts,
      invoices: enInvoices,
    },
  },
  lng: browserLanguage,
  fallbackLng: "nl",
  defaultNS: "common",
  ns: [
    "common",
    "login",
    "settings",
    "dashboard",
    "ticket_detail",
    "create_ticket",
    "reports",
    "extra_work",
    "planned_work",
    "staff_slots",
    "staff_credentials",
    "contracts",
    "invoices",
  ],
  interpolation: {
    escapeValue: false,
  },
  returnNull: false,
  react: {
    // Every page binds `useTranslation(["<page>", "common"])`, which only
    // means "fall back to common" when nsMode says so. Without this,
    // react-i18next binds `t` to namespaces[0] alone
    // (react-i18next/useTranslation.js: `nsMode === "fallback" ? namespaces
    // : namespaces[0]`), so any key that lives in common.json renders as its
    // own key name. That is how `archive.show`, `archive.show_working`,
    // `period.label` and `change.moved_to` reached the owner's screen.
    nsMode: "fallback",
  },
});

export default i18n;
