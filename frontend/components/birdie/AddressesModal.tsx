"use client";

import { useState } from "react";
import { XIcon, MapPinIcon, PlusIcon, Loader2Icon } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { useBirdieStore, type SavedAddress } from "@/lib/store";
import { API_URL } from "@/lib/constants";

interface Props {
  open: boolean;
  onClose: () => void;
}

export function AddressesModal({ open, onClose }: Props) {
  const savedAddresses = useBirdieStore((s) => s.savedAddresses);
  const addAddress = useBirdieStore((s) => s.addAddress);
  const removeAddress = useBirdieStore((s) => s.removeAddress);
  const setLocation = useBirdieStore((s) => s.setLocation);
  const [adding, setAdding] = useState(false);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleAdd = async () => {
    if (!input.trim()) return;
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`${API_URL}/api/geocode`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ address: input.trim() }),
      });
      if (!res.ok) throw new Error("Address not found");
      const data = await res.json();
      addAddress({ label: data.formatted_address || input.trim(), lat: data.lat, lng: data.lng });
      setInput("");
      setAdding(false);
    } catch {
      setError("Could not find this address. Try a different one.");
    } finally {
      setLoading(false);
    }
  };

  const selectAsDefault = (addr: SavedAddress) => {
    setLocation({ lat: addr.lat, lng: addr.lng });
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
            className="fixed inset-x-4 top-1/2 z-[60] mx-auto max-h-[80vh] max-w-[450px] -translate-y-1/2 overflow-y-auto rounded-[20px] bg-white p-6"
            style={{ boxShadow: "var(--b-shadow-lg)" }}
          >
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold" style={{ color: "var(--b-text)" }}>
                My Addresses
              </h2>
              <button onClick={onClose} className="rounded-lg p-1 hover:bg-gray-100">
                <XIcon className="size-5" style={{ color: "var(--b-text-secondary)" }} />
              </button>
            </div>

            <div className="mt-4">
              {savedAddresses.length === 0 && !adding ? (
                <div className="py-8 text-center text-sm" style={{ color: "var(--b-text-secondary)" }}>
                  <MapPinIcon className="mx-auto mb-2 size-8 opacity-40" />
                  <p>No saved addresses yet.</p>
                  <p className="mt-1">Add an address to quickly find nearby providers.</p>
                </div>
              ) : (
                <div className="space-y-2">
                  {savedAddresses.map((addr) => (
                    <div
                      key={addr.label}
                      className="flex items-center gap-2 rounded-xl p-3 transition-colors hover:bg-gray-50"
                      style={{ background: "var(--b-bg-light)" }}
                    >
                      <MapPinIcon className="size-4 shrink-0" style={{ color: "var(--b-text-accent)" }} />
                      <button
                        onClick={() => selectAsDefault(addr)}
                        className="min-w-0 flex-1 text-left text-sm"
                        style={{ color: "var(--b-text)" }}
                      >
                        <span className="block truncate">{addr.label}</span>
                      </button>
                      <button
                        onClick={() => removeAddress(addr.label)}
                        className="shrink-0 rounded-full p-1 transition-colors hover:bg-red-50"
                        style={{ color: "var(--b-text-secondary)" }}
                      >
                        <XIcon className="size-3.5" />
                      </button>
                    </div>
                  ))}
                </div>
              )}

              {/* Add new address */}
              {adding ? (
                <div className="mt-3 space-y-2">
                  <input
                    type="text"
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handleAdd()}
                    placeholder="Enter address..."
                    className="birdie-input"
                    autoFocus
                  />
                  {error && <p className="text-xs" style={{ color: "var(--b-error)" }}>{error}</p>}
                  <div className="flex gap-2">
                    <button
                      onClick={() => { setAdding(false); setInput(""); setError(""); }}
                      className="flex-1 rounded-3xl border py-2 text-sm font-medium hover:bg-gray-50"
                      style={{ borderColor: "var(--b-border)", color: "var(--b-text-secondary)" }}
                    >
                      Cancel
                    </button>
                    <button
                      onClick={handleAdd}
                      disabled={loading || !input.trim()}
                      className="birdie-btn-primary flex flex-1 items-center justify-center gap-1.5 !py-2 !text-sm disabled:opacity-50"
                    >
                      {loading ? <Loader2Icon className="size-4 animate-spin" /> : "Add"}
                    </button>
                  </div>
                </div>
              ) : (
                <button
                  onClick={() => setAdding(true)}
                  className="mt-3 flex w-full items-center justify-center gap-1.5 rounded-3xl border-2 border-dashed py-2.5 text-sm font-medium transition-colors hover:bg-[var(--b-bg-light)]"
                  style={{ borderColor: "var(--b-border)", color: "var(--b-text-secondary)" }}
                >
                  <PlusIcon className="size-4" />
                  Add new address
                </button>
              )}
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
