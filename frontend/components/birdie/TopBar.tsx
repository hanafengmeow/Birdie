"use client";

import { useTranslation } from "react-i18next";
import { useBirdieStore } from "@/lib/store";
import { MenuIcon, SettingsIcon, UploadIcon, BirdIcon } from "lucide-react";

interface TopBarProps {
  onToggleSidebar: () => void;
  onOpenUpload: () => void;
  onOpenSettings: () => void;
}

export function TopBar({ onToggleSidebar, onOpenUpload, onOpenSettings }: TopBarProps) {
  const { t } = useTranslation();
  const planJson = useBirdieStore((s) => s.planJson);
  const hydrated = useBirdieStore((s) => s._hydrated);
  const hasPlan = hydrated && planJson !== null;

  return (
    <header className="birdie-topbar flex items-center justify-between px-3">
      {/* Left: hamburger (mobile) + logo */}
      <div className="flex items-center gap-2">
        <button
          onClick={onToggleSidebar}
          className="flex size-9 items-center justify-center rounded-lg transition-colors hover:bg-gray-100 md:hidden"
          aria-label="Menu"
        >
          <MenuIcon className="size-5" style={{ color: "var(--b-text)" }} />
        </button>
        <BirdIcon className="size-7" style={{ color: "var(--b-text-accent)" }} />
        <span className="text-lg font-bold" style={{ color: "var(--b-text)" }}>
          Birdie
        </span>
      </div>

      {/* Right: plan status + settings */}
      <div className="flex items-center gap-1">
        {!hasPlan && (
          <button
            onClick={onOpenUpload}
            className="flex items-center gap-1 rounded-lg px-2 py-1.5 text-sm font-medium transition-colors hover:bg-gray-100"
            style={{ color: "var(--b-text-accent)" }}
          >
            <UploadIcon className="size-4" />
            <span className="hidden sm:inline">{t("topbar.upload_plan")}</span>
          </button>
        )}
        {hasPlan && (
          <span className="mr-1 flex items-center gap-1.5 text-xs" style={{ color: "var(--b-success)" }}>
            <span className="size-2 rounded-full" style={{ background: "var(--b-success)" }} />
            {t("topbar.plan_loaded")}
          </span>
        )}
        <button
          onClick={onOpenSettings}
          className="flex size-9 items-center justify-center rounded-lg transition-colors hover:bg-gray-100"
          aria-label="Settings"
        >
          <SettingsIcon className="size-5" style={{ color: "var(--b-text-secondary)" }} />
        </button>
      </div>
    </header>
  );
}
