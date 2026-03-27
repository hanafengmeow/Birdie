"use client";

import { XIcon, MapPinIcon, PhoneIcon } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

export interface SavedProvider {
  name: string;
  care_type?: string;
  address?: string;
  phone?: string | null;
  google_maps_url?: string;
  rating?: number | null;
  rating_count?: number | null;
}

interface Props {
  open: boolean;
  onClose: () => void;
  providers: SavedProvider[];
  onRemove: (name: string) => void;
}

export function SavedProvidersModal({ open, onClose, providers, onRemove }: Props) {
  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="fixed inset-0 z-50 bg-black/40"
            onClick={onClose}
          />
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.95 }}
            transition={{ duration: 0.3, ease: "easeOut" }}
            className="fixed inset-x-4 top-1/2 z-[60] mx-auto max-h-[80vh] w-auto max-w-[500px] -translate-y-1/2 overflow-y-auto rounded-[20px] bg-white p-6"
            style={{ boxShadow: "var(--b-shadow-lg)" }}
          >
            <div className="flex items-center justify-between">
              <h2 className="text-xl font-bold" style={{ color: "var(--b-text)" }}>
                Saved Providers
              </h2>
              <button onClick={onClose} className="rounded-lg p-1 transition-colors hover:bg-gray-100">
                <XIcon className="size-5" style={{ color: "var(--b-text-secondary)" }} />
              </button>
            </div>

            <div className="mt-4">
              {providers.length === 0 ? (
                <div className="py-10 text-center text-sm" style={{ color: "var(--b-text-secondary)" }}>
                  <p>No saved providers yet.</p>
                  <p className="mt-1">Start saving providers when you search for care!</p>
                </div>
              ) : (
                <div className="space-y-3">
                  {providers.map((p) => (
                    <div
                      key={p.name}
                      className="rounded-xl p-4 transition-colors hover:bg-gray-50"
                      style={{ background: "var(--b-bg-light)" }}
                    >
                      <div className="text-base font-bold" style={{ color: "var(--b-text)" }}>{p.name}</div>
                      {p.care_type && (
                        <div className="text-xs" style={{ color: "var(--b-text-secondary)" }}>{p.care_type}</div>
                      )}
                      {p.address && (
                        <div className="mt-1 text-[13px]" style={{ color: "var(--b-text-secondary)" }}>{p.address}</div>
                      )}
                      {p.rating != null && (
                        <div className="mt-1 text-[13px]" style={{ color: "var(--b-text-secondary)" }}>
                          {"\u2B50"} {p.rating} ({p.rating_count ?? 0} reviews)
                        </div>
                      )}
                      <div className="mt-3 flex items-center gap-2">
                        {p.phone && (
                          <a href={`tel:${p.phone}`}
                            className="inline-flex items-center gap-1 rounded-xl border px-3 py-2 text-sm transition-colors hover:bg-gray-50"
                            style={{ borderColor: "var(--b-border)" }}>
                            <PhoneIcon className="size-3" /> Call
                          </a>
                        )}
                        {p.google_maps_url && (
                          <a href={p.google_maps_url} target="_blank" rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 rounded-xl border px-3 py-2 text-sm transition-colors hover:bg-gray-50"
                            style={{ borderColor: "var(--b-border)" }}>
                            <MapPinIcon className="size-3" /> Maps
                          </a>
                        )}
                        <button
                          onClick={() => onRemove(p.name)}
                          className="ml-auto rounded-full p-1 transition-colors hover:bg-red-50"
                          style={{ color: "var(--b-text-secondary)" }}
                        >
                          <XIcon className="size-4 hover:text-red-500" />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
