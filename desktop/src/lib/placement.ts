// Presentation logic for the plate-placement check.
//
// Free of JSX so the rules a novice depends on stay testable: what the headline
// says, when the fix button may appear at all, and how an object's overhang
// reads in plain words instead of four numbers.

import type { PlacementCheck, PlacementItem } from "@/api";

export type PlacementTone = "ok" | "warn" | "blocked" | "unknown";

export interface PlacementVerdict {
  tone: PlacementTone;
  headline: string;
  canFix: boolean;
}

/**
 * The one-line answer.
 *
 * "blocked" means objects are off the plate and Studio will not move them —
 * either because a single move cannot fix it, or because moving would be a
 * guess. That distinction is what stops a half-fixed project.
 */
export function placementVerdict(check: PlacementCheck | null): PlacementVerdict {
  if (!check) return { tone: "unknown", headline: "Checking object placement…", canFix: false };
  if (!check.available) {
    return {
      tone: "unknown",
      headline: check.reason ?? "Studio could not check where the objects sit.",
      canFix: false,
    };
  }
  const repeated = check.items.some((entry) => (entry.instance_count ?? 1) > 1);
  if (check.off_plate.length === 0) {
    const many = (check.item_count ?? 0) > 1;
    return {
      tone: "ok",
      headline: repeated
        ? "Every placed instance sits inside the U1's printable area."
        : many
          ? "Every object sits inside the U1's printable area."
          : "The object sits inside the U1's printable area.",
      canFix: false,
    };
  }
  const count = check.off_plate.length;
  // A repeated object is one object at several places: count the places.
  const noun = repeated
    ? count === 1
      ? "placed instance is"
      : "placed instances are"
    : count === 1
      ? "object is"
      : "objects are";
  return {
    tone: check.fixable ? "warn" : "blocked",
    headline: `${count} ${noun} outside the U1's printable area.`,
    canFix: check.fixable,
  };
}

/** "Object 1", or "Object 1 · instance 2 of 3" when the same object is placed more than once. */
export function itemLabel(item: PlacementItem): string {
  const total = item.instance_count ?? 1;
  if (total <= 1) return `Object ${item.object_id}`;
  return `Object ${item.object_id} · instance ${(item.instance_index ?? 0) + 1} of ${total}`;
}

/** How far off, and which way — as a sentence rather than four numbers. */
export function overhangText(item: PlacementItem): string {
  const parts = (["left", "right", "front", "back"] as const)
    .filter((edge) => item.overhang_mm[edge] > 0)
    .map((edge) => `${item.overhang_mm[edge].toFixed(1)} mm past the ${edge} edge`);
  if (parts.length === 0) return "On the plate.";
  if (parts.length === 1) return `Hangs ${parts[0]}.`;
  return `Hangs ${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}.`;
}

/** Why Studio is refusing to move things, when it is. */
export function blockedReason(check: PlacementCheck | null): string | null {
  if (!check?.available || check.fixable || check.off_plate.length === 0) return null;
  if (check.unresolved_objects?.length) {
    return "Some objects are not listed on any plate, so Studio cannot tell where they belong.";
  }
  if (check.skipped_plates?.length) {
    return "At least one plate will not fit a U1 plate. Studio moves every plate or none.";
  }
  return "Moving the objects as one piece would not bring them all on, so Studio will not guess.";
}
