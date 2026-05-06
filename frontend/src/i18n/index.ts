import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import nlCommon from "./nl/common.json";
import nlLogin from "./nl/login.json";
import nlSettings from "./nl/settings.json";
import enCommon from "./en/common.json";
import enLogin from "./en/login.json";
import enSettings from "./en/settings.json";

// Default language is "nl" so unauthenticated routes (Login) render in Dutch.
// Once the user is authenticated, useLanguageSync re-fires changeLanguage
// based on me.language. The local storage cache key is intentionally not
// configured — language is sourced from /auth/me/, not from the browser.
i18n.use(initReactI18next).init({
  resources: {
    nl: { common: nlCommon, login: nlLogin, settings: nlSettings },
    en: { common: enCommon, login: enLogin, settings: enSettings },
  },
  lng: "nl",
  fallbackLng: "nl",
  defaultNS: "common",
  ns: ["common", "login", "settings"],
  interpolation: {
    escapeValue: false,
  },
  returnNull: false,
});

export default i18n;
