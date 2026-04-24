// i18n init for Chronos viewer
// Default language: Chinese (per user preference). Falls back to English.
import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import zh from "./zh";
import en from "./en";

void i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      zh: { translation: zh },
      en: { translation: en },
    },
    // Default to Chinese if detector returns nothing usable
    fallbackLng: "zh",
    // Supported languages (detector will only match these)
    supportedLngs: ["zh", "en"],
    interpolation: { escapeValue: false },
    detection: {
      // Order of detection sources
      order: ["localStorage", "navigator"],
      // Persist to localStorage so next visit stays on the chosen lang
      caches: ["localStorage"],
      lookupLocalStorage: "chronos.lang",
    },
  });

export default i18n;
