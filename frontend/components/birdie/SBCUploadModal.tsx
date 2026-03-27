"use client";

import { useCallback, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { XIcon, UploadIcon, Loader2Icon, CheckCircleIcon, AlertCircleIcon } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { useBirdieStore, type PlanJson } from "@/lib/store";

interface PlanLookupResponse {
  plan_json: PlanJson;
  plan_raw_text: string;
  plan_name: string;
}
import { API_URL } from "@/lib/constants";

type State = "idle" | "uploading" | "success" | "error";

interface Props {
  open: boolean;
  onClose: () => void;
}

export function SBCUploadModal({ open, onClose }: Props) {
  const { t } = useTranslation();
  const setPlanJson = useBirdieStore((s) => s.setPlanJson);
  const setPlanRawText = useBirdieStore((s) => s.setPlanRawText);
  const existingPlan = useBirdieStore((s) => s.planJson);
  const hydrated = useBirdieStore((s) => s._hydrated);
  const hasExistingPlan = hydrated && existingPlan !== null;
  const [state, setState] = useState<State>("idle");
  const [error, setError] = useState("");
  const [result, setResult] = useState<PlanJson | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const upload = useCallback(
    async (file: File) => {
      if (file.type !== "application/pdf") {
        setError(t("upload.only_pdf"));
        setState("error");
        return;
      }
      setState("uploading");
      setError("");
      try {
        const form = new FormData();
        form.append("file", file);
        const res = await fetch(`${API_URL}/api/plan-lookup`, { method: "POST", body: form });
        if (!res.ok) throw new Error(await res.text());
        const data = (await res.json()) as PlanLookupResponse;
        // Store plan_name inside plan_json for sidebar/UI display
        const planJson = {
          ...data.plan_json,
          plan_name: { value: data.plan_name, page: null, bbox: null, source_text: null },
        };
        setPlanJson(planJson);
        setPlanRawText(data.plan_raw_text);
        setResult(planJson);
        setState("success");
      } catch (e) {
        setError(e instanceof Error ? e.message : t("upload.error"));
        setState("error");
      }
    },
    [setPlanJson, setPlanRawText, t],
  );

  const handleDone = () => {
    onClose();
    // Reset state so next open is fresh
    setTimeout(() => { setState("idle"); setResult(null); }, 200);
  };

  const handleRetry = () => {
    setState("idle");
    setError("");
    setResult(null);
  };

  /** Extract a human-readable plan name from the parsed plan JSON. */
  const getPlanName = (plan: PlanJson): string => {
    // Check for an explicit plan_name field
    if (plan.plan_name?.value && typeof plan.plan_name.value === "string") {
      return plan.plan_name.value;
    }
    // Fall back to insurer_phone source_text (often contains the plan/insurer name)
    if (plan.insurer_phone?.source_text) {
      const cleaned = String(plan.insurer_phone.source_text)
        .replace(/Questions\? Call /i, "")
        .split(":")[0]
        .trim();
      if (cleaned) return cleaned;
    }
    return "Your insurance plan";
  };

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-[60] bg-black/40"
            onClick={handleDone}
          />
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.95 }}
            transition={{ duration: 0.3, ease: "easeOut" }}
            className="fixed inset-x-4 top-1/2 z-[60] mx-auto max-w-[500px] -translate-y-1/2 rounded-[20px] bg-white p-6"
            style={{ boxShadow: "var(--b-shadow-lg)" }}
          >
            {/* Header */}
            <div className="flex items-center justify-between">
              <h2 className="text-xl font-bold" style={{ color: "var(--b-text)" }}>
                {hasExistingPlan && state === "idle" ? "Change Plan" : t("upload.title")}
              </h2>
              <button onClick={handleDone} className="rounded-lg p-1 hover:bg-gray-100">
                <XIcon className="size-5" style={{ color: "var(--b-text-secondary)" }} />
              </button>
            </div>

            <div className="mt-4">
              {/* Show current plan if exists */}
              {state === "idle" && hasExistingPlan && existingPlan && (
                <div className="mb-4 rounded-xl p-3" style={{ background: "var(--b-bg-light)" }}>
                  <div className="text-xs font-medium uppercase tracking-wide" style={{ color: "var(--b-text-secondary)" }}>
                    Current Plan
                  </div>
                  <div className="mt-1 text-sm font-semibold" style={{ color: "var(--b-text)" }}>
                    {getPlanName(existingPlan)}
                  </div>
                </div>
              )}

              {/* Idle */}
              {state === "idle" && (
                <div
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={(e) => { e.preventDefault(); const f = e.dataTransfer.files?.[0]; if (f) upload(f); }}
                  onClick={() => inputRef.current?.click()}
                  className="flex cursor-pointer flex-col items-center gap-3 rounded-xl border-2 border-dashed p-10 text-center transition-colors hover:border-[var(--b-primary-start)] hover:bg-[var(--b-bg-light)]"
                  style={{ borderColor: "var(--b-border)" }}
                >
                  <UploadIcon className="size-10" style={{ color: "var(--b-text-secondary)" }} />
                  <p className="text-sm" style={{ color: "var(--b-text-secondary)" }}>
                    {t("upload.description")}
                  </p>
                  <input ref={inputRef} type="file" accept="application/pdf" className="hidden"
                    onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f); }} />
                </div>
              )}

              {/* Uploading */}
              {state === "uploading" && (
                <div className="flex flex-col items-center gap-4 py-10">
                  <Loader2Icon className="size-10 animate-spin" style={{ color: "var(--b-primary-start)" }} />
                  <p className="text-sm" style={{ color: "var(--b-text-secondary)" }}>{t("upload.processing")}</p>
                  <div className="h-1 w-full overflow-hidden rounded-full" style={{ background: "var(--b-border)" }}>
                    <div className="h-full animate-pulse rounded-full" style={{ background: "var(--b-primary-gradient)", width: "60%" }} />
                  </div>
                </div>
              )}

              {/* Success */}
              {state === "success" && result && (
                <div className="flex flex-col items-center text-center py-4">
                  <CheckCircleIcon className="size-10" style={{ color: "var(--b-success)" }} />
                  <span className="mt-3 text-lg font-semibold" style={{ color: "var(--b-success)" }}>
                    {t("upload.success")}
                  </span>
                  <span className="mt-2 text-sm font-medium" style={{ color: "var(--b-text)" }}>
                    {getPlanName(result)}
                  </span>
                  <button onClick={handleDone} className="birdie-btn-primary mt-6">
                    Got it, let&apos;s chat!
                  </button>
                </div>
              )}

              {/* Error */}
              {state === "error" && (
                <div className="flex flex-col items-center gap-3 py-6">
                  <AlertCircleIcon className="size-10" style={{ color: "var(--b-error)" }} />
                  <p className="text-sm font-medium" style={{ color: "var(--b-error)" }}>
                    {error || t("upload.error")}
                  </p>
                  <button onClick={handleRetry}
                    className="rounded-3xl border-2 px-6 py-2 text-sm font-medium transition-colors hover:bg-gray-50"
                    style={{ borderColor: "var(--b-primary-start)", color: "var(--b-primary-start)" }}>
                    Try again
                  </button>
                </div>
              )}
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
