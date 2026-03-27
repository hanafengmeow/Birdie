"use client";

import { useState, useEffect } from "react";
import { HeartIcon, MapPinIcon, PhoneIcon, StarIcon, CopyIcon, CheckIcon } from "lucide-react";
import { useTranslation } from "react-i18next";

interface Provider {
  name: string;
  address?: string;
  distance_miles?: number;
  is_open_now?: boolean;
  hours_today?: string;
  phone?: string | null;
  google_maps_url?: string;
  rating?: number | null;
  rating_count?: number | null;
  note?: string;
  insurer_url?: string;
  copay?: string;
  confidence?: string;
}

const SAVED_KEY = "birdie_saved_providers";

function getSaved(): Provider[] {
  try { return JSON.parse(localStorage.getItem(SAVED_KEY) || "[]"); } catch { return []; }
}
function setSaved(list: Provider[]) {
  localStorage.setItem(SAVED_KEY, JSON.stringify(list));
  window.dispatchEvent(new Event("birdie_saved_update"));
}

export function ProviderCard({ provider }: { provider: Provider }) {
  const { t } = useTranslation();
  const isTelehealth = provider.name === "Telehealth via your insurance";
  const [saved, setSavedState] = useState(false);
  const [animating, setAnimating] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    setSavedState(getSaved().some((p) => p.name === provider.name));
  }, [provider.name]);

  const toggleSave = () => {
    const current = getSaved();
    if (saved) {
      setSaved(current.filter((p) => p.name !== provider.name));
      setSavedState(false);
    } else {
      setSaved([...current, provider]);
      setSavedState(true);
      setAnimating(true);
      setTimeout(() => setAnimating(false), 300);
    }
  };

  const copyName = () => {
    navigator.clipboard.writeText(provider.name);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  if (isTelehealth) {
    return (
      <div className="birdie-provider-card my-3">
        <div className="text-base font-bold" style={{ color: "var(--b-text)" }}>
          {t("provider.telehealth_title")}
        </div>
        <p className="mt-1 text-sm" style={{ color: "var(--b-text-secondary)" }}>
          {provider.note || t("provider.telehealth_note")}
        </p>
        {provider.copay && (
          <p className="mt-1 text-sm">Copay: <span className="font-medium">{provider.copay}</span></p>
        )}
        {provider.insurer_url && (
          <a href={provider.insurer_url} target="_blank" rel="noopener noreferrer"
            className="mt-2 inline-block text-sm font-medium underline underline-offset-2"
            style={{ color: "var(--b-text-accent)" }}>
            {provider.insurer_url}
          </a>
        )}
      </div>
    );
  }

  return (
    <div className="birdie-provider-card my-3 animate-slide-up">
      {/* Name + copy + heart */}
      <div className="flex items-start justify-between">
        <div className="text-lg font-bold" style={{ color: "var(--b-text)" }}>{provider.name}</div>
        <div className="flex items-center gap-1 flex-shrink-0">
          <button onClick={copyName} className="p-1" aria-label="Copy provider name">
            {copied ? (
              <CheckIcon className="size-3.5" style={{ color: "var(--b-success)" }} />
            ) : (
              <CopyIcon className="size-3.5" style={{ color: "var(--b-text-secondary)" }} />
            )}
          </button>
          <button onClick={toggleSave} className="p-1">
            <HeartIcon
              className={`size-6 transition-all duration-200 ${animating ? "animate-heart" : ""}`}
              style={{
                color: saved ? "var(--b-primary-end)" : "var(--b-border)",
                fill: saved ? "var(--b-primary-end)" : "none",
              }}
            />
          </button>
        </div>
      </div>

      {/* Rating + distance */}
      <div className="mt-1 flex flex-wrap items-center gap-x-3 text-sm" style={{ color: "var(--b-text-secondary)" }}>
        {provider.rating != null && (
          <span className="inline-flex items-center gap-0.5">
            <StarIcon className="size-3.5 fill-amber-400 text-amber-400" />
            {provider.rating}
            {provider.rating_count != null && <span>({provider.rating_count} {t("provider.reviews")})</span>}
          </span>
        )}
        {provider.distance_miles != null && (
          <span>{provider.distance_miles.toFixed(1)} {t("provider.miles")}</span>
        )}
      </div>

      {/* Open status */}
      <div className="mt-1.5 text-sm">
        {provider.is_open_now ? (
          <span style={{ color: "var(--b-success)" }}>
            <span className="mr-1 inline-block size-2 rounded-full" style={{ background: "var(--b-success)" }} />
            {provider.hours_today || t("provider.open")}
          </span>
        ) : (
          <span style={{ color: "var(--b-error)" }}>
            <span className="mr-1 inline-block size-2 rounded-full" style={{ background: "var(--b-error)" }} />
            {t("provider.closed")}
          </span>
        )}
      </div>

      {/* Address */}
      {provider.address && (
        <div className="mt-1 text-sm" style={{ color: "var(--b-text-secondary)" }}>{provider.address}</div>
      )}

      {/* Insurance warning */}
      <div className="mt-3 rounded px-3 py-2 text-xs italic"
        style={{
          background: "rgba(212, 160, 96, 0.08)",
          borderLeft: "3px solid var(--b-caution)",
          color: "var(--b-caution)",
        }}>
        {"\u26A0\uFE0F"} {t("provider.verify_note")}
      </div>

      {/* Action buttons */}
      <div className="mt-3 grid grid-cols-2 gap-2">
        {provider.phone ? (
          <a href={`tel:${provider.phone}`}
            className="flex items-center justify-center gap-1.5 rounded-xl border py-3 text-sm font-medium transition-colors hover:bg-[var(--b-bg-light)]"
            style={{ borderColor: "var(--b-border)" }}>
            <PhoneIcon className="size-3.5" /> {t("provider.call")}
          </a>
        ) : <div />}
        {provider.google_maps_url ? (
          <a href={provider.google_maps_url} target="_blank" rel="noopener noreferrer"
            className="flex items-center justify-center gap-1.5 rounded-xl border py-3 text-sm font-medium transition-colors hover:bg-[var(--b-bg-light)]"
            style={{ borderColor: "var(--b-border)" }}>
            <MapPinIcon className="size-3.5" /> Maps
          </a>
        ) : <div />}
      </div>
    </div>
  );
}
