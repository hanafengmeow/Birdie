"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { XIcon, MapPinIcon, NavigationIcon, PencilIcon, Loader2Icon, CheckIcon } from "lucide-react";
import { useBirdieStore, type SavedAddress } from "@/lib/store";
import { API_URL } from "@/lib/constants";

interface Props {
  open: boolean;
  onClose: () => void;
  onLocationSelected: (loc: { lat: number; lng: number }) => void;
}

export function LocationModal({ open, onClose, onLocationSelected }: Props) {
  const savedAddresses = useBirdieStore((s) => s.savedAddresses);
  const setLocation = useBirdieStore((s) => s.setLocation);
  const addAddress = useBirdieStore((s) => s.addAddress);
  const [mode, setMode] = useState<"choose" | "enter">("choose");
  const [addressInput, setAddressInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const selectAddress = (addr: SavedAddress) => {
    const loc = { lat: addr.lat, lng: addr.lng };
    setLocation(loc);
    onLocationSelected(loc);
    onClose();
  };

  const useGPS = () => {
    setLoading(true);
    setError("");
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        const loc = { lat: pos.coords.latitude, lng: pos.coords.longitude };
        setLocation(loc);

        // Reverse geocode to get a human-readable address
        let label = "Current location";
        try {
          const res = await fetch(`${API_URL}/api/geocode`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ lat: loc.lat, lng: loc.lng }),
          });
          if (res.ok) {
            const data = await res.json();
            if (data.formatted_address) {
              label = data.formatted_address;
            }
          }
        } catch {
          // Reverse geocode failed — fall back to generic label
        }

        addAddress({ label, ...loc });
        setLoading(false);
        onLocationSelected(loc);
        onClose();
      },
      (err) => {
        setLoading(false);
        setError(err.code === 1 ? "Location access denied. Please enter an address." : "Could not get location. Please enter an address.");
        setMode("enter");
      },
      { enableHighAccuracy: true, timeout: 10000 },
    );
  };

  const geocodeAddress = async () => {
    if (!addressInput.trim()) return;
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`${API_URL}/api/geocode`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ address: addressInput.trim() }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({ detail: "Address not found" }));
        throw new Error(data.detail || "Address not found");
      }
      const data = await res.json();
      const loc = { lat: data.lat, lng: data.lng };
      setLocation(loc);
      addAddress({ label: data.formatted_address || addressInput.trim(), ...loc });
      setLoading(false);
      onLocationSelected(loc);
      onClose();
    } catch (e) {
      setLoading(false);
      setError(e instanceof Error ? e.message : "Failed to find address");
    }
  };

  const handleClose = () => {
    setMode("choose");
    setAddressInput("");
    setError("");
    setLoading(false);
    onClose();
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
            onClick={handleClose}
          />
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.95 }}
            transition={{ duration: 0.3, ease: "easeOut" }}
            className="fixed inset-x-4 top-1/2 z-[60] mx-auto max-w-[420px] -translate-y-1/2 rounded-[20px] bg-white p-6"
            style={{ boxShadow: "var(--b-shadow-lg)" }}
          >
            {/* Header */}
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold" style={{ color: "var(--b-text)" }}>
                <MapPinIcon className="mr-1.5 inline size-5" style={{ color: "var(--b-text-accent)" }} />
                Choose location
              </h2>
              <button onClick={handleClose} className="rounded-lg p-1 hover:bg-gray-100">
                <XIcon className="size-5" style={{ color: "var(--b-text-secondary)" }} />
              </button>
            </div>

            <div className="mt-4 space-y-3">
              {/* Saved addresses */}
              {mode === "choose" && savedAddresses.length > 0 && (
                <div>
                  <div className="mb-2 text-xs font-medium uppercase tracking-wide" style={{ color: "var(--b-text-secondary)" }}>
                    Recent locations
                  </div>
                  <div className="space-y-1.5">
                    {savedAddresses.map((addr) => (
                      <button
                        key={addr.label}
                        onClick={() => selectAddress(addr)}
                        className="flex w-full items-center gap-2 rounded-xl px-3 py-2.5 text-left text-sm transition-colors hover:bg-[var(--b-bg-light)]"
                        style={{ color: "var(--b-text)" }}
                      >
                        <MapPinIcon className="size-4 shrink-0" style={{ color: "var(--b-text-accent)" }} />
                        <span className="truncate">{addr.label}</span>
                        <CheckIcon className="ml-auto size-3.5 shrink-0 opacity-0 group-hover:opacity-100" />
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* GPS button */}
              {mode === "choose" && (
                <button
                  onClick={useGPS}
                  disabled={loading}
                  className="birdie-btn-primary flex items-center justify-center gap-2 !py-3 !text-sm"
                >
                  {loading ? (
                    <Loader2Icon className="size-4 animate-spin" />
                  ) : (
                    <NavigationIcon className="size-4" />
                  )}
                  Use my current location
                </button>
              )}

              {/* Enter address button / form */}
              {mode === "choose" && (
                <button
                  onClick={() => setMode("enter")}
                  className="flex w-full items-center justify-center gap-2 rounded-3xl border-2 py-3 text-sm font-bold transition-colors hover:bg-gray-50"
                  style={{ borderColor: "var(--b-primary-start)", color: "var(--b-primary-start)" }}
                >
                  <PencilIcon className="size-4" />
                  Enter an address
                </button>
              )}

              {/* Address input form */}
              {mode === "enter" && (
                <div className="space-y-3">
                  <input
                    type="text"
                    value={addressInput}
                    onChange={(e) => setAddressInput(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && geocodeAddress()}
                    placeholder="e.g. 360 Huntington Ave, Boston"
                    className="birdie-input"
                    autoFocus
                  />
                  <div className="flex gap-2">
                    <button
                      onClick={() => setMode("choose")}
                      className="flex-1 rounded-3xl border py-2.5 text-sm font-medium transition-colors hover:bg-gray-50"
                      style={{ borderColor: "var(--b-border)", color: "var(--b-text-secondary)" }}
                    >
                      Back
                    </button>
                    <button
                      onClick={geocodeAddress}
                      disabled={loading || !addressInput.trim()}
                      className="birdie-btn-primary flex flex-1 items-center justify-center gap-2 !py-2.5 !text-sm disabled:opacity-50"
                    >
                      {loading ? <Loader2Icon className="size-4 animate-spin" /> : "Search"}
                    </button>
                  </div>
                </div>
              )}

              {/* Error */}
              {error && (
                <p className="text-center text-xs" style={{ color: "var(--b-error)" }}>
                  {error}
                </p>
              )}
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
