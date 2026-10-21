// Pure logic for "a model you downloaded in the Studio Model Browser arrived in your library".
//
// The Model Browser's page has no Studio IPC. When the user downloads an STL or 3MF there,
// the desktop shell saves it into a Studio-controlled folder and tells the main window; this
// module turns the sidecar's answer into the "Added from <site>" card. Studio never fetches
// the file itself and never sees the site's cookies or password.

/** Sent by the shell when a browser-initiated download finished successfully. */
export interface ModelDownloadEvent {
  path: string;
  filename: string;
  /** Hostname of the page the download came from (never a URL with a query or token). */
  site: string;
  /** Page URL without query or fragment, https only; empty when unavailable. */
  page_url: string;
  title: string;
}

/** The sidecar's answer to `POST /library/register_download`. */
export interface RegisteredModel {
  ok: boolean;
  project_id?: number;
  name?: string;
  filename?: string;
  site?: string;
  site_name?: string;
  sha256?: string;
  size_bytes?: number;
  source_family?: string | null;
  verdict?: string | null;
  /** True when Studio would refuse to prepare this readable file. */
  prepare_blocked?: boolean;
  filament_count?: number | null;
  is_u1?: boolean | null;
  ready_hint?: string | null;
  message?: string;
  error?: string;
}

export interface AddedItem {
  path: string;
  projectId: number | null;
  name: string;
  siteName: string;
  heading: string;
  facts: string[];
  needsPrepare: boolean;
}

export const MAX_RECENT = 5;

const SITE_NAMES: [string, string][] = [
  ["printables.com", "Printables"],
  ["thingiverse.com", "Thingiverse"],
  ["myminifactory.com", "MyMiniFactory"],
  ["cults3d.com", "Cults3D"],
  ["thangs.com", "Thangs"],
  ["makerworld.com", "MakerWorld"],
];

/** "www.printables.com" -> "Printables". An unknown host is shown as typed, never invented. */
export function siteDisplayName(host: string): string {
  const h = (host || "").toLowerCase();
  for (const [domain, name] of SITE_NAMES) {
    if (h === domain || h.endsWith(`.${domain}`)) return name;
  }
  return h || "the site";
}

const FAMILY_LABELS: Record<string, string> = {
  bambu: "Bambu Studio project",
  orca: "OrcaSlicer project",
  snapmaker_orca: "Snapmaker Orca project",
  prusa: "PrusaSlicer project",
  generic: "Plain model (no slicer project settings)",
  u1: "Snapmaker U1 project",
};

export function familyLabel(family: string | null | undefined): string | null {
  if (!family) return null;
  return FAMILY_LABELS[family] ?? null;
}

function verdictFact(r: RegisteredModel): string | null {
  if (r.prepare_blocked) return "Studio can't prepare a U1 copy of this file yet — open it in Snapmaker Orca to review it.";
  switch (r.verdict) {
    case "READY": return "Profile compatible with the U1.";
    case "REPAIRABLE": return "Made for another printer or needs a few fixes — Studio can prepare a U1 copy.";
    case null:
    case undefined: return null;
    default: return "Needs attention before it can be prepared.";
  }
}

export function isRegistered(r: RegisteredModel | null | undefined): boolean {
  return !!r && r.ok === true && typeof r.project_id === "number";
}

/** Facts for the card come only from what the sidecar actually detected. */
export function toAddedItem(path: string, r: RegisteredModel): AddedItem {
  const siteName = r.site_name || siteDisplayName(r.site || "");
  const name = r.name || r.filename || "model";
  const facts: string[] = [];
  const fam = familyLabel(r.source_family);
  if (fam) facts.push(fam);
  if (typeof r.filament_count === "number" && r.filament_count > 0) {
    facts.push(`${r.filament_count} filament${r.filament_count === 1 ? "" : "s"} in the project`);
  }
  const v = verdictFact(r);
  if (v) facts.push(v);
  return {
    path,
    projectId: r.project_id ?? null,
    name,
    siteName,
    heading: `Added from ${siteName}`,
    facts,
    needsPrepare: r.verdict !== "READY" && !r.prepare_blocked,
  };
}

/** Newest first, one entry per file, capped. */
export function pushRecent(list: AddedItem[], item: AddedItem): AddedItem[] {
  return [item, ...list.filter((i) => i.path !== item.path)].slice(0, MAX_RECENT);
}

export function refusalMessage(filename: string): string {
  const name = filename ? `"${filename}"` : "That download";
  return `${name} was not added. Studio imports .3mf and .stl files — download one of those from the site.`;
}

export function failureMessage(detail?: string): string {
  return detail
    ? `Studio could not add that download: ${detail}`
    : "Studio could not add that download to your library.";
}

export const SITE_DATA_COPY = {
  signIn:
    "Sign in on the site itself. Studio never sees your password or cookies. " +
    "Sign-in is stored on this computer by the Model Connect browser.",
  clear:
    "Clear site data signs you out of every site and deletes the Model Browser's cookies and " +
    "cache. It does not touch Studio's own settings, your library or your files.",
} as const;
