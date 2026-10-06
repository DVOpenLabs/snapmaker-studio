// Trusted Studio-side control surface for the locked Model Browser window.
// The remote approved-site page stays in an isolated, no-IPC Tauri window; every
// control lives here in trusted Studio UI. No scraping, no auto-import, no API keys.

export const MODEL_BROWSER_COPY = {
  flow: "Browse in the Studio Model Browser and download the STL/3MF the usual way. Studio adds it to your library, then you can check it for your U1 with Project Doctor.",
  openTitle: "Model Browser is open",
  closedHint: "Pick a site above to open it in the Studio Model Browser.",
  trust:
    "Approved sites only, in a locked Studio-owned window. You sign in on the site itself — " +
    "Studio never sees your password or cookies, never scrapes pages, never fetches files " +
    "itself, and never bypasses a site's login or terms. No API keys are needed.",
} as const;

/** What happens, in order, when you use Model Connect. Said once, the same on every site. */
export const MODEL_CONNECT_STEPS = [
  "Browse or search for a model",
  "Use the site's normal download button",
  "Studio adds supported downloads to your Library",
  "Ready Now checks it against your U1",
] as const;

export interface BrowserPanelState {
  open: boolean;
  site: string | null; // human label of the site currently open in-app
}

export const closedPanel: BrowserPanelState = { open: false, site: null };

/** Heading for the control panel, reflecting the live window state. */
export function panelLabel(s: BrowserPanelState): string {
  return s.open && s.site
    ? `Model Browser is open — browsing ${s.site}`
    : "Model Browser is closed";
}

/** Show the trusted control panel only once a site has been opened in-app. */
export function showPanel(s: BrowserPanelState): boolean {
  return s.open;
}
