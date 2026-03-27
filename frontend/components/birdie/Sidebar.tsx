"use client";

import { useState, useEffect } from "react";
import { useBirdieStore, getChatHistory, getCurrentConversationId, formatRelativeTime, type ChatHistoryEntry } from "@/lib/store";
import {
  ChevronDownIcon,
  HeartIcon,
  PlusIcon,
  SettingsIcon,
  LogOutIcon,
  XIcon,
  BirdIcon,
  HistoryIcon,
  RefreshCwIcon,
  MapPinIcon,
} from "lucide-react";

interface SidebarProps {
  open: boolean;
  onClose: () => void;
  onOpenUpload: () => void;
  onOpenSaved: () => void;
  onOpenAddresses: () => void;
  onOpenSettings: () => void;
  savedCount: number;
  addressCount: number;
}

export function Sidebar({ open, onClose, onOpenUpload, onOpenSaved, onOpenAddresses, onOpenSettings, savedCount, addressCount }: SidebarProps) {
  const planJson = useBirdieStore((s) => s.planJson);
  const hydrated = useBirdieStore((s) => s._hydrated);
  const hasPlan = hydrated && planJson !== null;
  const [historyOpen, setHistoryOpen] = useState(true);
  const [historyItems, setHistoryItems] = useState<ChatHistoryEntry[]>([]);

  useEffect(() => {
    setHistoryItems(getChatHistory());
  }, []);

  // Listen for new history entries added during this session
  useEffect(() => {
    const handler = () => setHistoryItems(getChatHistory());
    window.addEventListener("birdie_history_updated", handler);
    return () => window.removeEventListener("birdie_history_updated", handler);
  }, []);

  return (
    <>
      {/* Dark overlay (mobile only) — z-40 */}
      {open && (
        <div
          className="fixed inset-0 z-40 bg-black/40 transition-opacity md:hidden"
          onClick={onClose}
        />
      )}

      {/* Sidebar panel */}
      <aside
        className={`birdie-sidebar birdie-scroll fixed inset-y-0 left-0 z-50 flex flex-col transition-transform duration-300 ease-in-out md:relative md:z-auto md:translate-x-0 ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        {/* Mobile close header */}
        <div className="flex h-14 items-center justify-between px-4 md:hidden">
          <div className="flex items-center gap-2">
            <BirdIcon className="size-5" style={{ color: "var(--b-text-accent)" }} />
            <span className="text-base font-bold" style={{ color: "var(--b-text-accent)" }}>
              Birdie
            </span>
          </div>
          <button onClick={onClose} className="rounded-lg p-1.5 transition-colors hover:bg-gray-100">
            <XIcon className="size-5" style={{ color: "var(--b-text-secondary)" }} />
          </button>
        </div>

        {/* Profile / Plan */}
        <div className="border-b px-4 pb-4 pt-3" style={{ borderColor: "var(--b-border)" }}>
          <div className="flex items-center gap-2">
            <BirdIcon className="hidden size-5 md:block" style={{ color: "var(--b-text-accent)" }} />
            <span className="hidden text-base font-bold md:block" style={{ color: "var(--b-text-accent)" }}>
              Birdie
            </span>
          </div>
          <div className="mt-1 text-sm font-medium leading-snug" style={{ color: "var(--b-text)" }}>
            {hasPlan
              ? (planJson?.plan_name?.value && typeof planJson.plan_name.value === "string"
                  ? planJson.plan_name.value
                  : "Insurance Plan Loaded")
              : "No plan uploaded"}
          </div>
          <button
            onClick={() => { onClose(); onOpenUpload(); }}
            className="mt-3 flex w-full items-center justify-center gap-1.5 rounded-[20px] border px-4 py-2 text-sm font-medium transition-colors hover:bg-gray-50"
            style={{ borderColor: "var(--b-primary-start)", color: "var(--b-primary-start)" }}
          >
            <RefreshCwIcon className="size-3.5" />
            {hasPlan ? "Change Plan" : "Select Plan"}
          </button>
        </div>

        {/* New Chat */}
        <div className="px-4 pt-4">
          <button
            onClick={() => window.location.reload()}
            className="birdie-btn-primary flex items-center justify-center gap-2 !py-3 !text-sm"
          >
            <PlusIcon className="size-4" />
            New Chat
          </button>
        </div>

        {/* History */}
        <div className="mt-4 px-4">
          <button
            onClick={() => setHistoryOpen(!historyOpen)}
            className="flex w-full items-center justify-between py-2 text-sm font-medium"
            style={{ color: "var(--b-text-secondary)" }}
          >
            <span className="flex items-center gap-1.5">
              <HistoryIcon className="size-4" /> History
            </span>
            <ChevronDownIcon className={`size-4 transition-transform duration-200 ${historyOpen ? "rotate-180" : ""}`} />
          </button>
          {historyOpen && (
            <div className="space-y-0.5 pb-2">
              {historyItems.length === 0 ? (
                <div
                  className="px-3 py-2 text-sm italic"
                  style={{ color: "var(--b-text-secondary)", opacity: 0.6 }}
                >
                  No conversations yet
                </div>
              ) : (
                historyItems.map((item) => {
                  const isCurrent = item.id === getCurrentConversationId();
                  return (
                    <button
                      key={item.id}
                      onClick={() => {
                        if (isCurrent) return;
                        // Set this conversation as current and reload with its messages
                        sessionStorage.setItem("birdie_current_conv_id", item.id);
                        sessionStorage.setItem("birdie_load_conv", JSON.stringify(item.messages || []));
                        window.location.reload();
                      }}
                      className={`w-full rounded-lg px-3 py-2 text-left text-sm transition-colors ${
                        isCurrent ? "bg-[var(--b-bg-light)]" : "hover:bg-[var(--b-bg-light)]"
                      }`}
                      style={{ color: isCurrent ? "var(--b-text)" : "var(--b-text-secondary)" }}
                    >
                      <div className="truncate">{item.title}</div>
                      <div className="mt-0.5 text-xs" style={{ opacity: 0.5 }}>
                        {isCurrent ? "Current" : formatRelativeTime(item.timestamp)}
                      </div>
                    </button>
                  );
                })
              )}
            </div>
          )}
        </div>

        {/* Saved Providers — same level as History */}
        <div className="mt-2 px-4">
          <button
            onClick={() => { onClose(); onOpenSaved(); }}
            className="flex w-full items-center justify-between py-2 text-sm font-medium"
            style={{ color: "var(--b-text-secondary)" }}
          >
            <span className="flex items-center gap-1.5">
              <HeartIcon className="size-4" style={{ color: "var(--b-error)" }} />
              Saved Providers ({savedCount})
            </span>
            <ChevronDownIcon className="size-4 -rotate-90" />
          </button>
        </div>

        {/* My Addresses — same level as Saved Providers */}
        <div className="mt-2 px-4">
          <button
            onClick={() => { onClose(); onOpenAddresses(); }}
            className="flex w-full items-center justify-between py-2 text-sm font-medium"
            style={{ color: "var(--b-text-secondary)" }}
          >
            <span className="flex items-center gap-1.5">
              <MapPinIcon className="size-4" style={{ color: "var(--b-text-accent)" }} />
              My Addresses ({addressCount})
            </span>
            <ChevronDownIcon className="size-4 -rotate-90" />
          </button>
        </div>

        <div className="flex-1" />

        {/* Bottom */}
        <div className="border-t px-4 py-3" style={{ borderColor: "var(--b-border)" }}>
          <button
            onClick={() => { onClose(); onOpenSettings(); }}
            className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm transition-colors hover:bg-[var(--b-bg-light)]"
            style={{ color: "var(--b-text-secondary)" }}
          >
            <SettingsIcon className="size-4" />
            Settings
          </button>
          <button
            onClick={() => window.location.reload()}
            className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm transition-colors hover:bg-red-50"
            style={{ color: "var(--b-error)" }}
          >
            <LogOutIcon className="size-4" />
            Log Out
          </button>
        </div>
      </aside>
    </>
  );
}
