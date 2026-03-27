"use client";

import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useTranslation } from "react-i18next";
import { UploadIcon } from "lucide-react";

interface WelcomeScreenProps {
  onDismiss: () => void;
  onUpload: () => void;
}

export function WelcomeScreen({ onDismiss, onUpload }: WelcomeScreenProps) {
  const { t } = useTranslation();
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    if (typeof window !== "undefined") {
      const shown = sessionStorage.getItem("birdie_welcome_shown");
      if (shown) { setVisible(false); onDismiss(); return; }
    }
    // No auto-dismiss — stay until user clicks a button
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const dismiss = () => {
    setVisible(false);
    if (typeof window !== "undefined") {
      sessionStorage.setItem("birdie_welcome_shown", "true");
    }
    onDismiss();
  };

  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          initial={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
          className="fixed inset-0 z-50 flex flex-col items-center justify-end"
          style={{
            backgroundImage: "url('/open.gif')",
            backgroundSize: "cover",
            backgroundPosition: "center",
          }}
        >
          {/* Hero text — positioned in center area */}
          <div className="flex flex-1 items-center justify-center">
            <motion.h1
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.8, ease: "easeOut" }}
              className="animate-glow select-none text-center"
              style={{
                fontFamily: "var(--font-pacifico), cursive",
                fontSize: "clamp(56px, 16vw, 80px)",
                color: "#fff",
                letterSpacing: "2px",
              }}
            >
              Birdie
            </motion.h1>
          </div>

          {/* Buttons at bottom */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.5, duration: 0.4 }}
            className="flex w-full max-w-sm flex-col gap-3 px-6 pb-12"
          >
            <button
              onClick={onUpload}
              className="birdie-btn-primary flex items-center justify-center gap-2"
            >
              <UploadIcon className="size-5" />
              {t("welcome.upload_cta")}
            </button>
            <button
              onClick={dismiss}
              className="w-full rounded-3xl border-2 border-white/70 bg-white/10 py-[14px] text-base font-bold text-white backdrop-blur-sm transition-all hover:bg-white/20"
            >
              {t("welcome.ask_cta")}
            </button>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
