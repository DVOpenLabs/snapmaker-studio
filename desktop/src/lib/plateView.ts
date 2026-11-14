// What the job screen's plate drawing may show, decided from the placement check alone.
//
// Free of JSX so the rule stays testable: positions are drawn only when Studio
// established them. A project with several plates, an unreadable one, or one with an
// instance Studio could not judge is never drawn as if its objects were placed.

import type { PlacementCheck } from "@/api";
import { itemLabel, unjudgedCount } from "@/lib/placement";

export interface PlateRect {
  key: string;
  label: string;
  /** Millimetres from the bed's left edge and from its front edge. */
  x: number;
  y: number;
  w: number;
  h: number;
  off: boolean;
}

export type PlateModel =
  | { kind: "loading" }
  /** No drawing: the reason is the whole message. */
  | { kind: "none"; reason: string }
  | { kind: "drawn"; width: number; depth: number; bedName: string; rects: PlateRect[] };

export function plateModel(check: PlacementCheck | null): PlateModel {
  if (!check) return { kind: "loading" };
  if (!check.available) return { kind: "none", reason: check.reason ?? "Studio could not read where the objects sit." };
  if ((check.plate_count ?? 1) > 1 || check.placement_established === false) {
    return { kind: "none", reason: "This project has several plates. Studio does not establish where they sit, so none are drawn." };
  }
  if (unjudgedCount(check) > 0) {
    return { kind: "none", reason: "Some placed instances could not be judged, so the plate is not drawn." };
  }
  const bed = check.bed;
  if (!bed || !(bed.max_x > bed.min_x) || !(bed.max_y > bed.min_y)) {
    return { kind: "none", reason: "Studio did not get the printable area, so the plate is not drawn." };
  }
  const rects: PlateRect[] = [];
  for (const item of check.items) {
    const b = item.bounds_mm;
    if (!b || b.min.length < 2 || b.max.length < 2 || ![...b.min.slice(0, 2), ...b.max.slice(0, 2)].every(Number.isFinite)) {
      return { kind: "none", reason: "An object's extent was not reported, so the plate is not drawn." };
    }
    rects.push({
      key: `${item.object_id}:${item.item_index ?? 0}`,
      label: itemLabel(item),
      x: b.min[0] - bed.min_x, y: b.min[1] - bed.min_y,
      w: b.max[0] - b.min[0], h: b.max[1] - b.min[1],
      off: item.off_plate,
    });
  }
  return {
    kind: "drawn", width: bed.max_x - bed.min_x, depth: bed.max_y - bed.min_y,
    bedName: check.bed_name ?? "the printer's", rects,
  };
}
