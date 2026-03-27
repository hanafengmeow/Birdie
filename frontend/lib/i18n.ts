"use client";

import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import en from "@/public/locales/en/common.json";
import zh from "@/public/locales/zh/common.json";

/** Detect saved or browser language. Only call on the client after hydration. */
export function detectLanguage(): string {
  if (typeof window === "undefined") return "en";
  try {
    const stored = localStorage.getItem("birdie_language");
    if (stored === "zh" || stored === "en") return stored;
  } catch {
    // localStorage unavailable
  }
  const nav = navigator.language.slice(0, 2);
  return nav === "zh" ? "zh" : "en";
}

// Always init with "en" so server and client match during hydration.
// After hydration, the app calls i18n.changeLanguage(detectLanguage()).
i18n.use(initReactI18next).init({
  resources: {
    en: { common: en },
    zh: { common: zh },
  },
  lng: "en",
  fallbackLng: "en",
  ns: ["common"],
  defaultNS: "common",
  interpolation: { escapeValue: false },
});

export default i18n;
