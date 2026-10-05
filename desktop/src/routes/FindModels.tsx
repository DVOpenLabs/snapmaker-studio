import { useState, useEffect } from "react";
import { useMutation } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  Search, ExternalLink, Loader2, Lock, Info, Compass, FolderOpen, Stethoscope, X, RotateCw,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/layout";
import {
  openModelBrowser, closeModelBrowser, isModelBrowserOpen, focusModelBrowser, modelSearch,
  clearModelBrowserData,
} from "@/api";
import { AddedFromCard } from "@/components/AddedFromCard";
import { useModelDownloads } from "@/store/modelDownloads";
import { SITE_DATA_COPY } from "@/lib/modelDownloads";
import { useMode } from "@/store/mode";
import { useOpenFile } from "@/hooks/useOpenFile";
import { MODEL_BROWSER_COPY, panelLabel, showPanel, closedPanel, type BrowserPanelState } from "@/lib/modelBrowser";
import {
  filterResults, linkOutUrl, importReasonLabel, DISCLAIMER, BROWSE_PROVIDERS,
  SANCTIONED_SOURCES, type SearchFilters, type SearchResponse, type ModelSource,
} from "@/lib/modelSearch";

const FORMATS = ["STL", "3MF"];

// Find Models is the trusted control center. Approved model sites open in a
// SEPARATE Studio-owned window ("Snapmaker Studio — Model Browser") that is
// allowlist-locked and gets NO Tauri IPC. (A single-window embed is not viable
// on this Tauri/wry stack — add_child deadlocks — so the site lives in its own
// locked Studio window and every control stays here in trusted Studio UI.)
export default function FindModels() {
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState<SearchFilters>({});
  const [resp, setResp] = useState<SearchResponse | null>(null);
  const advanced = useMode((s) => s.mode) === "advanced";
  const openFile = useOpenFile();

  // Live state of the locked Model Browser window + which site we last opened.
  const [panel, setPanel] = useState<BrowserPanelState>(closedPanel);
  const [siteId, setSiteId] = useState<string | null>(null);

  const providerLabel = (id: string) => BROWSE_PROVIDERS.find((p) => p.id === id)?.label ?? id;

  // What arrived from the Model Browser, and the two-step "Clear site data".
  const recent = useModelDownloads((s) => s.recent);
  const refusal = useModelDownloads((s) => s.refusal);
  const failure = useModelDownloads((s) => s.failure);
  const [confirmClear, setConfirmClear] = useState(false);
  const [clearNote, setClearNote] = useState<string | null>(null);
  async function clearSiteData() {
    try {
      await clearModelBrowserData();
      setClearNote("Site data cleared. You are signed out of the model sites.");
    } catch {
      setClearNote("Site data could not be cleared (this needs the desktop app).");
    }
    setConfirmClear(false);
  }

  // Open (or re-point) the locked Model Browser window at an approved site.
  async function browse(id: string) {
    const url = linkOutUrl(id, query);
    try {
      await openModelBrowser(url);
      setSiteId(id);
      setPanel({ open: true, site: providerLabel(id) });
    } catch {
      // Not in the desktop app (e.g. dev in a plain browser) — fall back to a tab.
      window.open(url, "_blank", "noreferrer");
    }
  }

  async function bringToFront() { try { await focusModelBrowser(); } catch { /* not desktop */ } }
  async function closeBrowser() {
    try { await closeModelBrowser(); } catch { /* not desktop */ }
    setPanel(closedPanel);
    setSiteId(null);
  }

  // Reflect the real window state: the user can close the Model Browser window
  // directly, so poll and keep the trusted panel in sync.
  useEffect(() => {
    const tick = async () => {
      try {
        const open = await isModelBrowserOpen();
        setPanel((p) => (p.open === open ? p : open ? p : closedPanel));
      } catch { /* not desktop */ }
    };
    const t = window.setInterval(tick, 1500);
    return () => window.clearInterval(t);
  }, []);

  const searchM = useMutation({
    mutationFn: () => modelSearch(query, { sources: filters.sources }),
    onSuccess: (d) => setResp(d),
  });
  function toggleSource(s: ModelSource) {
    setFilters((f) => { const c = new Set(f.sources ?? []); c.has(s) ? c.delete(s) : c.add(s); return { ...f, sources: [...c] }; });
  }
  function toggleFormat(fmt: string) {
    setFilters((f) => { const c = new Set(f.formats ?? []); c.has(fmt) ? c.delete(fmt) : c.add(fmt); return { ...f, formats: [...c] }; });
  }
  const shown = resp ? filterResults(resp.results, filters) : [];
  const chip = (on: boolean) => `rounded-md border px-2.5 py-1 text-xs ${on ? "border-foreground text-foreground" : "border-border text-muted-foreground"}`;

  return (
    <div className="space-y-6">
      <PageHeader icon={Compass} title="Find Models"
        subtitle="Browse approved model sites inside Studio." />

      {/* 1) Search term */}
      <Card><CardContent className="space-y-2 p-5">
        <p className="text-sm font-medium">What are you looking for?</p>
        <div className="flex gap-2">
          <input value={query} onChange={(e) => setQuery(e.target.value)}
            placeholder="e.g. desk organizer, U1 calibration cube…"
            className="flex-1 rounded-md border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary" />
          {advanced && (
            <Button size="sm" variant="secondary" onClick={() => searchM.mutate()} disabled={!query.trim() || searchM.isPending}>
              {searchM.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />} Search in-app
            </Button>
          )}
        </div>
        <p className="text-xs text-muted-foreground">Type a term (optional), then pick a site below to browse it in the Studio Model Browser.</p>
      </CardContent></Card>

      {/* 2) Approved site buttons */}
      <Card><CardContent className="space-y-2 p-5">
        <p className="text-sm font-semibold">Browse trusted model sites — in Studio</p>
        <p className="text-xs text-muted-foreground">{MODEL_BROWSER_COPY.flow}</p>
        <div className="flex flex-wrap gap-2 pt-1">
          {BROWSE_PROVIDERS.map((p) => (
            <Button key={p.id} size="sm" variant={siteId === p.id ? "primary" : "secondary"} onClick={() => browse(p.id)}>
              {siteId === p.id ? <RotateCw className="h-4 w-4" /> : <Compass className="h-4 w-4" />} {p.label}
            </Button>
          ))}
        </div>
        <p className="flex items-start gap-1.5 pt-1 text-[11px] text-muted-foreground">
          <Lock className="mt-0.5 h-3 w-3 shrink-0" /> {MODEL_BROWSER_COPY.trust}
        </p>
      </CardContent></Card>

      {/* 3) Control center — visible only while the locked window is open */}
      {showPanel(panel) && (
        <Card><CardContent className="space-y-2 p-5">
          <p className="flex items-center gap-1.5 text-sm font-semibold">
            <Compass className="h-4 w-4 text-primary" /> {panelLabel(panel)}
          </p>
          <p className="text-xs text-muted-foreground">
            The site is open in a separate, locked Snapmaker Studio window. Download the STL or 3MF
            there the usual way — Studio adds it to your library, and it appears below.
          </p>
          <div className="flex flex-wrap gap-2 pt-1">
            <Button size="sm" onClick={bringToFront}><ExternalLink className="h-4 w-4" /> Bring browser to front</Button>
            {siteId && (
              <Button size="sm" variant="secondary" onClick={() => browse(siteId)}>
                <RotateCw className="h-4 w-4" /> Reopen {providerLabel(siteId)}
              </Button>
            )}
            <Button size="sm" variant="secondary" onClick={closeBrowser}><X className="h-4 w-4" /> Close Model Browser</Button>
          </div>
        </CardContent></Card>
      )}

      {/* 3b) What the Model Browser just added to the library */}
      {(refusal || failure) && (
        <div role="status" className="rounded-md border border-border p-3 text-xs text-muted-foreground">
          <p className="flex items-start gap-1.5"><Info className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {refusal || failure}</p>
        </div>
      )}
      {recent.length > 0 && (
        <div className="space-y-2">
          <p className="text-sm font-semibold">Added from your downloads</p>
          {recent.map((item) => <AddedFromCard key={item.path} item={item} />)}
        </div>
      )}

      {/* 3c) Sign-in lives in the browser, not in Studio */}
      <Card><CardContent className="space-y-2 p-5">
        <p className="text-sm font-semibold">Signing in to model sites</p>
        <p className="text-xs text-muted-foreground">{SITE_DATA_COPY.signIn}</p>
        <p className="text-xs text-muted-foreground">{SITE_DATA_COPY.clear}</p>
        <div className="flex flex-wrap items-center gap-2 pt-1">
          {!confirmClear ? (
            <Button size="sm" variant="secondary" onClick={() => { setClearNote(null); setConfirmClear(true); }}>
              Clear site data…
            </Button>
          ) : (
            <>
              <Button size="sm" onClick={clearSiteData}>Yes, clear site data</Button>
              <Button size="sm" variant="secondary" onClick={() => setConfirmClear(false)}>Cancel</Button>
            </>
          )}
          {clearNote && <span role="status" className="text-xs text-muted-foreground">{clearNote}</span>}
        </div>
      </CardContent></Card>

      {/* 4) Downloaded file → Project Doctor (single, no duplicate) */}
      <Card><CardContent className="space-y-2 p-5">
        <p className="text-sm font-semibold">Got a downloaded file?</p>
        <p className="text-xs text-muted-foreground">Open the STL or 3MF you downloaded and Studio checks it for your U1.</p>
        <div className="flex flex-wrap gap-2 pt-1">
          <Button size="sm" onClick={openFile}><FolderOpen className="h-4 w-4" /> Open downloaded file</Button>
          <Button size="sm" variant="secondary" asChild><Link to="/doctor/project"><Stethoscope className="h-4 w-4" /> Run Project Doctor</Link></Button>
        </div>
      </CardContent></Card>

      {advanced && (
        <>
          <Card><CardContent className="space-y-3 p-5">
            <p className="text-sm font-medium">Advanced: live in-app search</p>
            <p className="text-xs text-muted-foreground">
              Optional. Live metadata search uses each provider's official API and needs a key
              configured outside the app; most users just browse above.
            </p>
            <div className="flex flex-wrap items-center gap-1.5">
              <button className={chip(!!filters.freeOnly)} onClick={() => setFilters((f) => ({ ...f, freeOnly: !f.freeOnly }))}>Free only</button>
              <button className={chip(!!filters.commercialUse)} onClick={() => setFilters((f) => ({ ...f, commercialUse: !f.commercialUse }))}>Commercial-use</button>
              <button className={chip(!!filters.multiColor)} onClick={() => setFilters((f) => ({ ...f, multiColor: !f.multiColor }))}>Multi-color</button>
              {FORMATS.map((fmt) => (
                <button key={fmt} className={chip((filters.formats ?? []).includes(fmt))} onClick={() => toggleFormat(fmt)}>{fmt}</button>
              ))}
              <span className="mx-1 text-[11px] text-muted-foreground">source:</span>
              {SANCTIONED_SOURCES.map((s) => (
                <button key={s} className={chip((filters.sources ?? []).includes(s))} onClick={() => toggleSource(s)}>{s}</button>
              ))}
            </div>
          </CardContent></Card>

          {resp && resp.warnings.length > 0 && (
            <div className="rounded-md border border-border p-3 text-xs text-muted-foreground">
              {resp.warnings.map((w, i) => (
                <p key={i} className="flex items-start gap-1.5"><Info className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {w}</p>
              ))}
            </div>
          )}

          {resp && shown.length > 0 && (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {shown.map((r, i) => (
                <Card key={`${r.source}-${i}`}><CardContent className="space-y-2 p-4">
                  {r.thumbnail_url && <img src={r.thumbnail_url} alt="" className="h-28 w-full rounded object-cover" />}
                  <p className="truncate text-sm font-medium" title={r.title}>{r.title}</p>
                  <p className="flex items-center justify-between text-xs text-muted-foreground">
                    <span>{r.source}</span>
                    <span>{r.price_status ?? "unknown"}{r.license ? ` · ${r.license}` : ""}</span>
                  </p>
                  {r.attribution && <p className="text-[11px] text-muted-foreground">by {r.attribution}</p>}
                  <div className="flex items-center gap-2 pt-1">
                    <Button size="sm" variant="secondary" asChild>
                      <a href={r.source_url} target="_blank" rel="noreferrer"><ExternalLink className="h-4 w-4" /> Open on source site</a>
                    </Button>
                  </div>
                  <p className="text-[11px] text-muted-foreground">
                    {r.import_allowed
                      ? "Studio doesn't download models — get it from the source site, then use Open model to check it."
                      : importReasonLabel(r.reason_import_not_allowed)}
                  </p>
                </CardContent></Card>
              ))}
            </div>
          )}
        </>
      )}

      <details className="text-xs text-muted-foreground">
        <summary className="cursor-pointer text-muted-foreground hover:text-foreground">How Studio handles sites</summary>
        <p className="mt-2 rounded-md bg-muted/40 p-3">
          Studio does not scrape pages, fetch files itself, or bypass site logins or terms. Sites open
          in a Studio-owned window that can only reach the approved sites and their sign-in and download
          hosts; anything else is blocked. When you download an STL or 3MF there, your browser saves it
          into a Studio folder and Studio adds it to your library. {DISCLAIMER}
        </p>
      </details>
    </div>
  );
}
