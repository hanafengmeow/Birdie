"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";
import {
  PLAN_CONTEXT_KEY,
  CHAT_HISTORY_KEY,
  MAX_HISTORY_ENTRIES,
  HISTORY_TITLE_MAX_LENGTH,
} from "./constants";

export interface PlanField {
  value: string | boolean | string[] | null;
  page: number | null;
  bbox: number[] | null;
  source_text: string | null;
  confidence?: string;
  value_b?: string | null;
}

export type PlanJson = Record<string, PlanField>;

export interface SavedAddress {
  label: string;           // formatted address
  lat: number;
  lng: number;
}

const MAX_SAVED_ADDRESSES = 5;

interface BirdieStore {
  planJson: PlanJson | null;
  planRawText: string | null;
  location: { lat: number; lng: number } | null;
  userLanguage: string;
  savedAddresses: SavedAddress[];
  _hydrated: boolean;
  setPlanJson: (plan: PlanJson | null) => void;
  setPlanRawText: (text: string | null) => void;
  setLocation: (loc: { lat: number; lng: number } | null) => void;
  setUserLanguage: (lang: string) => void;
  addAddress: (addr: SavedAddress) => void;
  removeAddress: (label: string) => void;
}

export const useBirdieStore = create<BirdieStore>()(
  persist(
    (set, get) => ({
      planJson: null,
      planRawText: null,
      location: null,
      userLanguage: "en",
      savedAddresses: [],
      _hydrated: false,
      setPlanJson: (plan) => set({ planJson: plan }),
      setPlanRawText: (text) => set({ planRawText: text }),
      setLocation: (loc) => set({ location: loc }),
      setUserLanguage: (lang) => set({ userLanguage: lang }),
      addAddress: (addr) => {
        const current = get().savedAddresses.filter((a) => a.label !== addr.label);
        const next = [addr, ...current].slice(0, MAX_SAVED_ADDRESSES);
        set({ savedAddresses: next });
      },
      removeAddress: (label) => {
        set({ savedAddresses: get().savedAddresses.filter((a) => a.label !== label) });
      },
    }),
    {
      name: PLAN_CONTEXT_KEY,
      partialize: (state) => ({
        planJson: state.planJson,
        planRawText: state.planRawText,
        location: state.location,
        userLanguage: state.userLanguage,
        savedAddresses: state.savedAddresses,
      }),
      onRehydrateStorage: () => (state) => {
        if (state) state._hydrated = true;
      },
    },
  ),
);

export function getBirdieContext() {
  const { planJson, planRawText, location, userLanguage } = useBirdieStore.getState();
  return {
    plan_json: planJson,
    plan_raw_text: planRawText,
    location,
    user_language: userLanguage,
  };
}

// ── Chat history (localStorage-only, not in Zustand) ──────────

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ChatHistoryEntry {
  id: string;
  title: string;
  timestamp: number;
  messages: ChatMessage[];
}

export function getChatHistory(): ChatHistoryEntry[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(CHAT_HISTORY_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed;
  } catch {
    return [];
  }
}

/** Get or create the current conversation ID for this session. */
export function getCurrentConversationId(): string {
  if (typeof window === "undefined") return "";
  let id = sessionStorage.getItem("birdie_current_conv_id");
  if (!id) {
    id = crypto.randomUUID();
    sessionStorage.setItem("birdie_current_conv_id", id);
  }
  return id;
}

/** Save/update the current conversation in history. Called after each message. */
export function saveConversation(messages: ChatMessage[]): void {
  if (typeof window === "undefined" || messages.length === 0) return;

  const id = getCurrentConversationId();
  const firstUserMsg = messages.find((m) => m.role === "user");
  const titleText = firstUserMsg?.content || "New conversation";
  const title =
    titleText.length > HISTORY_TITLE_MAX_LENGTH
      ? titleText.slice(0, HISTORY_TITLE_MAX_LENGTH) + "..."
      : titleText;

  const existing = getChatHistory().filter((e) => e.id !== id);
  const entry: ChatHistoryEntry = { id, title, timestamp: Date.now(), messages };
  const updated = [entry, ...existing].slice(0, MAX_HISTORY_ENTRIES);

  try {
    localStorage.setItem(CHAT_HISTORY_KEY, JSON.stringify(updated));
  } catch {
    // localStorage full — silently ignore
  }
}

/** Legacy function kept for compatibility — now calls saveConversation internally. */
export function addChatHistoryEntry(firstMessage: string): void {
  // Now handled by saveConversation
  void firstMessage;
}

export function formatRelativeTime(timestamp: number): string {
  const now = Date.now();
  const diffMs = now - timestamp;
  const diffSec = Math.floor(diffMs / 1000);
  const diffMin = Math.floor(diffSec / 60);
  const diffHr = Math.floor(diffMin / 60);
  const diffDay = Math.floor(diffHr / 24);

  if (diffSec < 60) return "Just now";
  if (diffMin < 60) return `${diffMin} min ago`;
  if (diffHr < 24) return `${diffHr} hour${diffHr === 1 ? "" : "s"} ago`;
  if (diffDay === 1) return "Yesterday";
  if (diffDay < 7) return `${diffDay} days ago`;
  return new Date(timestamp).toLocaleDateString();
}
