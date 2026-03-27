"use client";

import { useTranslation } from "react-i18next";

const STYLES: Record<string, { bg: string; text: string }> = {
  HIGH:     { bg: "var(--b-success)", text: "#fff" },
  MED:      { bg: "var(--b-caution)", text: "#fff" },
  CONFLICT: { bg: "var(--b-error)", text: "#fff" },
  MISSING:  { bg: "var(--b-text-secondary)", text: "#fff" },
};

export function ConfidencePill({ confidence }: { confidence: string }) {
  const { t } = useTranslation();
  const label = t(`confidence.${confidence}`, { defaultValue: "" }) || confidence;
  const style = STYLES[confidence] ?? STYLES.MISSING;

  return (
    <span
      className="inline-block whitespace-nowrap rounded-xl px-2 py-0.5 text-xs font-bold"
      style={{ background: style.bg, color: style.text }}
    >
      {label}
    </span>
  );
}
