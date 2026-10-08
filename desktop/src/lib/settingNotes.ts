import type { SettingsChange } from "@/api";

// What to tell a person about WHY one setting changed, using only what the engine already said.
//
// The engine writes two pieces of text for a change: a short `reason` and, for some steps, a plain-language `explanation`.
// This never invents wording. It prefers the explanation, falls back to a reason that says something specific, and says
// nothing when the reason only restates that the setting changed.
//
// Only compatibility changes are explained this way. Settings that were kept, and the optional recommendations, are
// different things and keep their own sections.
const RESTATES_THE_CHANGE = new Set([
  "changed only for U1 compatibility",
  "carried over to U1 toolheads (values preserved)",
  "available with the recommended U1 profile",
  "U1 machine profile setting applied",
]);

export function settingNote(change: SettingsChange): string | null {
  const explanation = change.explanation?.trim();
  if (explanation) return explanation;
  const reason = change.reason?.trim();
  if (!reason) return null;
  // "U1 compatibility clamp: -1 → 5" only repeats the old and new values already on the line above it.
  if (RESTATES_THE_CHANGE.has(reason) || reason.startsWith("U1 compatibility clamp:")) return null;
  return reason;
}
