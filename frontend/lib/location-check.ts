"use client";

// Keywords that indicate the user wants to find a nearby provider
// (triggers location check before sending)
const LOCATION_KEYWORDS = [
  "near me",
  "nearby",
  "find.*care",
  "find.*clinic",
  "find.*pharmacy",
  "find.*doctor",
  "find.*hospital",
  "find.*urgent",
  "find.*er\\b",
  "find.*provider",
  "where.*go",
  "closest",
  "附近",
  "找.*诊所",
  "找.*药房",
  "找.*医院",
  "找.*急诊",
];

const LOCATION_REGEX = new RegExp(LOCATION_KEYWORDS.join("|"), "i");

export function needsLocation(text: string): boolean {
  return LOCATION_REGEX.test(text);
}

// Custom event to request location from page.tsx
export function requestLocation(pendingMessage: string) {
  window.dispatchEvent(
    new CustomEvent("birdie_need_location", { detail: { message: pendingMessage } }),
  );
}
