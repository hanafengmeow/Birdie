"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import i18n, { detectLanguage } from "@/lib/i18n";
import { WelcomeScreen } from "@/components/birdie/WelcomeScreen";
import { TopBar } from "@/components/birdie/TopBar";
import { Sidebar } from "@/components/birdie/Sidebar";
import { SBCUploadModal } from "@/components/birdie/SBCUploadModal";
import { SavedProvidersModal, type SavedProvider } from "@/components/birdie/SavedProvidersModal";
import { AddressesModal } from "@/components/birdie/AddressesModal";
import { LocationModal } from "@/components/birdie/LocationModal";
import { SettingsPanel } from "@/components/birdie/SettingsPanel";
import { Assistant } from "./assistant";
import { useBirdieStore } from "@/lib/store";

const SAVED_KEY = "birdie_saved_providers";

export default function Home() {
  const [mounted, setMounted] = useState(false);
  const [showWelcome, setShowWelcome] = useState(true);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploadFromWelcome, setUploadFromWelcome] = useState(false);
  const [savedOpen, setSavedOpen] = useState(false);
  const [addressesOpen, setAddressesOpen] = useState(false);
  const [locationModalOpen, setLocationModalOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [savedProviders, setSavedProviders] = useState<SavedProvider[]>([]);

  // Pending message waiting for location
  const pendingMessageRef = useRef<string | null>(null);

  const addressCount = useBirdieStore((s) => s.savedAddresses.length);

  const loadSaved = useCallback(() => {
    try {
      setSavedProviders(JSON.parse(localStorage.getItem(SAVED_KEY) || "[]"));
    } catch { setSavedProviders([]); }
  }, []);

  useEffect(() => {
    setMounted(true);
    loadSaved();

    // Sync i18n language after hydration to avoid SSR mismatch
    const detected = detectLanguage();
    if (i18n.language !== detected) {
      i18n.changeLanguage(detected);
    }

    const handleSavedUpdate = () => loadSaved();
    window.addEventListener("birdie_saved_update", handleSavedUpdate);

    // Listen for location requests from thread.tsx
    const handleNeedLocation = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      pendingMessageRef.current = detail?.message || null;
      setLocationModalOpen(true);
    };
    window.addEventListener("birdie_need_location", handleNeedLocation);

    return () => {
      window.removeEventListener("birdie_saved_update", handleSavedUpdate);
      window.removeEventListener("birdie_need_location", handleNeedLocation);
    };
  }, [loadSaved]);

  const removeSaved = (name: string) => {
    const next = savedProviders.filter((p) => p.name !== name);
    localStorage.setItem(SAVED_KEY, JSON.stringify(next));
    setSavedProviders(next);
    window.dispatchEvent(new Event("birdie_saved_update"));
  };

  const handleUploadClose = () => {
    setUploadOpen(false);
    if (uploadFromWelcome) {
      setUploadFromWelcome(false);
      setShowWelcome(false);
      if (typeof window !== "undefined") {
        sessionStorage.setItem("birdie_welcome_shown", "true");
      }
    }
  };

  // When location is selected from the modal, resend the pending message.
  // Small delay ensures Zustand store is fully updated before the message fires.
  const handleLocationSelected = () => {
    setLocationModalOpen(false);
    const msg = pendingMessageRef.current;
    pendingMessageRef.current = null;
    if (msg) {
      console.log("[page] dispatching birdie_send_message:", msg, "location:", useBirdieStore.getState().location);
      setTimeout(() => {
        window.dispatchEvent(
          new CustomEvent("birdie_send_message", { detail: { message: msg } }),
        );
      }, 100);
    }
  };

  if (!mounted) {
    return <div className="flex h-dvh items-center justify-center" />;
  }

  return (
    <>
      {showWelcome && (
        <WelcomeScreen
          onDismiss={() => setShowWelcome(false)}
          onUpload={() => {
            setUploadFromWelcome(true);
            setUploadOpen(true);
          }}
        />
      )}

      <SBCUploadModal open={uploadOpen} onClose={handleUploadClose} />
      <SavedProvidersModal
        open={savedOpen}
        onClose={() => setSavedOpen(false)}
        providers={savedProviders}
        onRemove={removeSaved}
      />
      <AddressesModal open={addressesOpen} onClose={() => setAddressesOpen(false)} />
      <LocationModal
        open={locationModalOpen}
        onClose={() => { setLocationModalOpen(false); pendingMessageRef.current = null; }}
        onLocationSelected={handleLocationSelected}
      />
      <SettingsPanel open={settingsOpen} onClose={() => setSettingsOpen(false)} />

      <div className="flex h-dvh flex-col">
        <TopBar
          onToggleSidebar={() => setSidebarOpen(!sidebarOpen)}
          onOpenUpload={() => setUploadOpen(true)}
          onOpenSettings={() => setSettingsOpen(true)}
        />

        <div className="flex flex-1 overflow-hidden">
          <Sidebar
            open={sidebarOpen}
            onClose={() => setSidebarOpen(false)}
            onOpenUpload={() => { setSidebarOpen(false); setUploadOpen(true); }}
            onOpenSaved={() => { setSidebarOpen(false); setSavedOpen(true); }}
            onOpenAddresses={() => { setSidebarOpen(false); setAddressesOpen(true); }}
            onOpenSettings={() => { setSidebarOpen(false); setSettingsOpen(true); }}
            savedCount={savedProviders.length}
            addressCount={addressCount}
          />

          <main className="flex flex-1 flex-col overflow-hidden">
            <Assistant />
          </main>
        </div>
      </div>
    </>
  );
}
