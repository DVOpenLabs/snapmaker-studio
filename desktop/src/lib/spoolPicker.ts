// Presentation and keyboard logic for the spool picker, free of JSX so every rule is testable.
//
// The rules that matter:
//  - a spool is described by words, never by a swatch alone: vendor, material, subtype,
//    colour NAME, the provider's id, and the weight status are always in the text;
//  - the order is the same every time (vendor, family, subtype, colour, id), whatever order
//    the provider answered in;
//  - typing narrows the list; arrow keys, Home/End, Enter and Escape drive it.

import type { ProviderSpool } from "@/api";
import { colorName } from "@/lib/plateRemapWizard";

export function weightStatus(spool: ProviderSpool): string {
  if (spool.remaining_g === null || spool.remaining_g === undefined) return "weight unknown";
  const amount = `${Math.round(spool.remaining_g)} g`;
  // Only a spool something has printed from, or has weighed, carries a figure anything keeps
  // up to date; the two are labelled apart here as well as in the engine.
  return spool.remaining_quality === "tracked" ? `${amount} tracked` : `${amount} estimated`;
}

function cap(s: string): string {
  return s.length ? s[0].toUpperCase() + s.slice(1) : s;
}

export function spoolColourName(spool: ProviderSpool): string | null {
  const given = (spool.color_name ?? "").trim();
  if (given) return cap(given);
  const computed = colorName(spool.color);
  return computed ? cap(computed) : null;
}

export interface SpoolDescription {
  swatch: string | null;
  name: string;          // "Yoopai PLA Matte"
  colour: string | null; // "Red"
  idText: string;        // "#124"
  weight: string;        // "250 g estimated"
  archived: boolean;
  /** The whole thing as one sentence of text, for screen readers and search. */
  text: string;
}

export function describeSpool(spool: ProviderSpool): SpoolDescription {
  const material = [spool.material, spool.subtype].filter(Boolean).join(" ");
  const name = [spool.vendor, material].filter(Boolean).join(" ") || spool.label || `Spool ${spool.id}`;
  const colour = spoolColourName(spool);
  const idText = `#${spool.id}`;
  const weight = weightStatus(spool);
  const archived = !!spool.archived;
  const text =
    `${name}${colour ? ` — ${colour}` : ""} · ${idText} · ${weight}${archived ? " · archived" : ""}`;
  return { swatch: spool.color ?? null, name, colour, idText, weight, archived, text };
}

function textKey(v: string | null | undefined): [number, string] {
  const s = (v ?? "").trim();
  return [s ? 0 : 1, s.toLowerCase()];
}

function cmp(a: [number, string], b: [number, string]): number {
  return a[0] - b[0] || (a[1] < b[1] ? -1 : a[1] > b[1] ? 1 : 0);
}

function idKey(id: number | string): [number, number, string] {
  const s = String(id);
  return /^\d+$/.test(s) ? [0, Number(s), ""] : [1, 0, s.toLowerCase()];
}

/** vendor → material family → subtype → colour → provider id. Never mutates its input. */
export function sortSpools(spools: ProviderSpool[]): ProviderSpool[] {
  return [...spools].sort((a, b) => {
    const c =
      cmp(textKey(a.vendor), textKey(b.vendor)) ||
      cmp(textKey(a.material), textKey(b.material)) ||
      cmp(textKey(a.subtype), textKey(b.subtype)) ||
      cmp(textKey(spoolColourName(a)), textKey(spoolColourName(b))) ||
      cmp(textKey(a.color), textKey(b.color));
    if (c) return c;
    const x = idKey(a.id), y = idKey(b.id);
    return x[0] - y[0] || x[1] - y[1] || (x[2] < y[2] ? -1 : x[2] > y[2] ? 1 : 0);
  });
}

/** Every word typed must appear somewhere in the spool's text, its id or its hex. */
export function filterSpools(spools: ProviderSpool[], query: string): ProviderSpool[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean).map((w) => w.replace(/^#/, ""));
  if (!words.length) return spools;
  return spools.filter((s) => {
    const hay = `${describeSpool(s).text} ${s.id} ${s.color ?? ""} ${s.label ?? ""}`.toLowerCase();
    return words.every((w) => hay.includes(w));
  });
}

// --- keyboard ----------------------------------------------------------------------

export interface ListboxState {
  open: boolean;
  query: string;
  /** Index into the visible options; -1 is the "nothing mapped" row. */
  active: number;
}

export type ListboxAction =
  | { type: "open"; selectedIndex: number }
  | { type: "close" }
  | { type: "move"; delta: 1 | -1; count: number }
  | { type: "home" }
  | { type: "end"; count: number }
  | { type: "type"; query: string };

export const initialListbox: ListboxState = { open: false, query: "", active: -1 };

export function listboxReduce(s: ListboxState, a: ListboxAction): ListboxState {
  switch (a.type) {
    case "open": return { open: true, query: "", active: a.selectedIndex };
    case "close": return { open: false, query: "", active: -1 };
    case "move": {
      if (!s.open) return { ...s, open: true };
      // -1 is the "nothing mapped" row; it wraps with the options.
      const total = a.count + 1;
      const next = ((s.active + 1 + a.delta + total) % total) - 1;
      return { ...s, active: next };
    }
    case "home": return { ...s, active: -1 };
    case "end": return { ...s, active: a.count - 1 };
    case "type": return { open: true, query: a.query, active: a.query ? 0 : -1 };
  }
}

/** Rendering every row of a long list is wasted work; the filter box is how you reach the rest. */
export const MAX_VISIBLE = 250;
