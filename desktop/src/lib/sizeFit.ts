// The "Bed fit" row of Design Health, as plain data so its wording stays testable.
//
// This row is a SIZE statement: how big each object is against the bed. It says nothing about where
// anything sits, so it always begins "By size" and points at the placement check for position. The
// combined extents of several separated objects or plates are never read as one big object.

import type { ObjectSize } from "@/api";

export type SizeLevel = "ok" | "warn" | "risk";

export interface Bed {
  x: number;
  y: number;
  z: number;
}

export interface SizeRow {
  level: SizeLevel;
  status: string;
  detail: string;
}

type Dims = { x: number; y: number; z: number };

const fitsBed = (d: Dims, bed: Bed) => d.x <= bed.x && d.y <= bed.y && d.z <= bed.z;
const mm = (d: Dims) => `${d.x} × ${d.y} × ${d.z} mm`;

export const UNMEASURED = "By size, Studio could not measure each object, so it cannot say whether they fit.";
const SIZE_ONLY = "Size only: where it sits on the plate is a separate check.";

/**
 * `overall` is the combined extents of all the mesh data. It is only a signal that there IS geometry:
 * it is never used to say an object fits or is too big, because for several separated objects or plates
 * it is not any one object's size. No per-object sizes means "unknown".
 */
export function sizeRow(
  objects: ObjectSize[] | null | undefined,
  overall: Dims | null | undefined,
  bed: Bed,
  bedSource: string,
  unmeasured = 0,
): SizeRow | null {
  const bedStr = `${bed.x} × ${bed.y} × ${bed.z} mm`;
  const sized = (objects ?? []).filter((o) => o.dimensions_mm);
  if (sized.length === 0) {
    if (!overall) return null;
    return { level: "warn", status: "Unknown", detail: UNMEASURED };
  }
  const missing =
    unmeasured > 0
      ? ` ${unmeasured} build item${unmeasured === 1 ? "" : "s"} could not be measured, so Studio cannot say whether everything fits.`
      : "";
  const tooBig = sized.filter((o) => !fitsBed(o.dimensions_mm, bed));
  const many = sized.length > 1;
  if (tooBig.length > 0) {
    const first = tooBig[0];
    const who = many && first.object_id != null ? `object ${first.object_id} (${mm(first.dimensions_mm)})` : mm(first.dimensions_mm);
    const more = tooBig.length > 1 ? ` ${tooBig.length} objects are larger than the bed.` : "";
    return {
      level: "risk",
      status: "Too big",
      detail: `By size, ${who} is larger than ${bedSource} ${bedStr} bed — scale it down or split it.${more}${missing}`,
    };
  }
  const largest = sized.reduce((a, b) => (b.dimensions_mm.x * b.dimensions_mm.y > a.dimensions_mm.x * a.dimensions_mm.y ? b : a));
  const subject = many
    ? `each of the ${sized.length} objects fits ${bedSource} ${bedStr} bed (the largest is ${mm(largest.dimensions_mm)})`
    : `${mm(largest.dimensions_mm)} fits ${bedSource} ${bedStr} bed`;
  return {
    level: missing ? "warn" : "ok",
    status: missing ? "Check" : "Fits",
    detail: `By size, ${subject}. ${SIZE_ONLY}${missing}`,
  };
}
