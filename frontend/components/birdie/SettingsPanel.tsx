"use client";

import { useTranslation } from "react-i18next";
import { useBirdieStore } from "@/lib/store";
import { XIcon, LogOutIcon } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

interface Props {
  open: boolean;
  onClose: () => void;
}

export function SettingsPanel({ open, onClose }: Props) {
  const { i18n } = useTranslation();
  const setUserLanguage = useBirdieStore((s) => s.setUserLanguage);
  const userLanguage = useBirdieStore((s) => s.userLanguage);

  const switchLang = (lang: string) => {
    i18n.changeLanguage(lang);
    setUserLanguage(lang);
    try { localStorage.setItem("birdie_language", lang); } catch {}
  };

  const handleLogout = () => {
    try { localStorage.clear(); } catch {}
    window.location.reload();
  };

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 bg-black/40"
            onClick={onClose}
          />
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.95 }}
            transition={{ duration: 0.3, ease: "easeOut" }}
            className="fixed inset-x-4 top-1/2 z-[60] mx-auto max-w-[400px] -translate-y-1/2 rounded-[20px] bg-white p-6"
            style={{ boxShadow: "var(--b-shadow-lg)" }}
          >
            <div className="flex items-center justify-between">
              <h2 className="text-xl font-bold" style={{ color: "var(--b-text)" }}>
                Settings
              </h2>
              <button onClick={onClose} className="rounded-lg p-1 hover:bg-gray-100">
                <XIcon className="size-5" style={{ color: "var(--b-text-secondary)" }} />
              </button>
            </div>

            {/* Language */}
            <div className="mt-5 border-t pt-4" style={{ borderColor: "var(--b-border)" }}>
              <div className="text-sm font-medium" style={{ color: "var(--b-text)" }}>Language</div>
              <div className="mt-2 flex gap-2">
                {(["en", "zh"] as const).map((lang) => (
                  <button
                    key={lang}
                    onClick={() => switchLang(lang)}
                    className="flex-1 rounded-xl py-2 text-sm font-medium transition-all"
                    style={{
                      background: userLanguage === lang ? "var(--b-primary-gradient)" : "var(--b-bg-light)",
                      color: userLanguage === lang ? "#fff" : "var(--b-text)",
                    }}
                  >
                    {lang === "en" ? "EN" : "\u4E2D\u6587"}
                  </button>
                ))}
              </div>
            </div>

            {/* Dark mode (mock) */}
            <div className="mt-4 border-t pt-4" style={{ borderColor: "var(--b-border)" }}>
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium" style={{ color: "var(--b-text)" }}>Dark Mode</span>
                <div
                  className="h-6 w-11 cursor-pointer rounded-full p-0.5"
                  style={{ background: "var(--b-border)" }}
                  onClick={() => console.log("Dark mode coming soon")}
                >
                  <div className="size-5 rounded-full bg-white shadow transition-transform" />
                </div>
              </div>
            </div>

            {/* Logout */}
            <div className="mt-4 border-t pt-4" style={{ borderColor: "var(--b-border)" }}>
              <button
                onClick={handleLogout}
                className="flex w-full items-center justify-center gap-2 rounded-xl py-3 text-sm font-bold text-white transition-opacity hover:opacity-90"
                style={{ background: "var(--b-error)" }}
              >
                <LogOutIcon className="size-4" />
                Log Out
              </button>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
