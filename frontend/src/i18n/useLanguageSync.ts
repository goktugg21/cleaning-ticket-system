import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "../auth/AuthContext";

// Watches me.language and switches i18next when it changes. Called once from
// AppShell so any authenticated layout has the correct language active. The
// dependency on me?.language re-fires after AuthContext.reloadMe() runs
// post-PATCH /auth/me/, which is what makes the "save Profile → switch
// language → instant re-render" flow work without a full page reload.
export function useLanguageSync() {
  const { me } = useAuth();
  const { i18n } = useTranslation();

  useEffect(() => {
    const target = me?.language === "en" ? "en" : "nl";
    if (i18n.language !== target) {
      i18n.changeLanguage(target);
    }
    // FE-7 (§D.6.9) — the document language follows the session, so
    // screen readers and the browser's own hyphenation/spell tools read
    // the page in the language it is actually in (index.html says "en").
    document.documentElement.lang = target;
  }, [me?.language, i18n]);
}
