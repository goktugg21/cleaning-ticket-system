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
import enCommon from "./en/common.json";
import enLogin from "./en/login.json";
import enSettings from "./en/settings.json";
import enDashboard from "./en/dashboard.json";
import enTicketDetail from "./en/ticket_detail.json";
import enCreateTicket from "./en/create_ticket.json";
import enReports from "./en/reports.json";
import enExtraWork from "./en/extra_work.json";

// Default language is "nl" so unauthenticated routes (Login) render in Dutch.
// Once the user is authenticated, useLanguageSync re-fires changeLanguage
// based on me.language. The local storage cache key is intentionally not
// configured — language is sourced from /auth/me/, not from the browser.
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
    },
  },
  lng: "nl",
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
  ],
  interpolation: {
    escapeValue: false,
  },
  returnNull: false,
});

export default i18n;
