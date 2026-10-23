import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { getCurrentWebview } from "@tauri-apps/api/webview";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { StatusBar } from "./StatusBar";
import { Toaster } from "@/components/ui/Toaster";
import { useSession } from "@/store/session";
import { useSliced } from "@/store/sliced";
import { shouldResetScroll } from "@/lib/scrollReset";
import { JOB_ROUTE } from "@/lib/routes";

function titleFor(path: string): string {
  if (path === "/") return "Home";
  if (path.startsWith("/this-print")) return "This job";
  if (path.startsWith("/after-slicing")) return "After slicing";
  if (path.startsWith("/workspace")) return "Workspace";
  if (path.startsWith("/batch")) return "Batch prepare";
  if (path.startsWith("/projects")) return "Projects";
  if (path.startsWith("/printers")) return "Printer Hub";
  if (path.startsWith("/settings")) return "Settings";
  return "Snapmaker Studio";
}

export function AppShell() {
  const { pathname, hash } = useLocation();
  const nav = useNavigate();
  const setFile = useSession((s) => s.setFile);
  const setSliced = useSliced((s) => s.setSliced);

  // Narrow windows: the sidebar becomes a drawer opened from a Menu button.
  const [menuOpen, setMenuOpen] = useState(false);
  const menuButton = useRef<HTMLButtonElement>(null);
  const drawer = useRef<HTMLDivElement>(null);
  const main = useRef<HTMLElement>(null);
  const focusPage = useRef(false);
  const closeMenu = useCallback((returnFocus = true) => {
    setMenuOpen(false);
    if (returnFocus) menuButton.current?.focus();
    else focusPage.current = true;     // chose a destination: focus goes to the page, not the Menu button
  }, []);
  // The scrolling element is <main>, not the window, so a new page must start at its top by hand.
  const lastPath = useRef<string | null>(null);
  useLayoutEffect(() => {
    if (shouldResetScroll(lastPath.current, pathname, hash) && main.current) main.current.scrollTop = 0;
    lastPath.current = pathname;
  }, [pathname, hash]);
  // A navigation (or a wider window) ends the drawer; focus follows the page, not the button.
  useEffect(() => { setMenuOpen(false); }, [pathname]);
  // After a destination is chosen the drawer closes and focus goes to the page, also when the route is unchanged.
  useEffect(() => {
    if (!menuOpen && focusPage.current) { focusPage.current = false; main.current?.focus({ preventScroll: true }); }
  }, [menuOpen, pathname]);
  useEffect(() => {
    if (!menuOpen) return;
    // First real destination, not the scrim.
    drawer.current?.querySelector<HTMLElement>("#nav-drawer button, #nav-drawer a[href]")?.focus();
    const media = window.matchMedia?.("(min-width: 768px)");
    const wide = () => { if (media?.matches) setMenuOpen(false); };
    media?.addEventListener?.("change", wide);
    return () => media?.removeEventListener?.("change", wide);
  }, [menuOpen]);
  const onDrawerKey = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") { e.stopPropagation(); closeMenu(); return; }
    if (e.key !== "Tab") return;
    // Keep Tab inside the open drawer.
    const items = [...(drawer.current?.querySelectorAll<HTMLElement>("a[href],button:not([disabled]):not([tabindex=\"-1\"]),summary,input") ?? [])];
    if (items.length === 0) return;
    const first = items[0], last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  };

  // Native drag-and-drop: a dropped .stl/.3mf loads into the live workspace.
  // Guarded so the app still renders outside Tauri (e.g. a plain browser for
  // screenshots) where the webview API is unavailable.
  useEffect(() => {
    let cleanup: (() => void) | undefined;
    try {
      const un = getCurrentWebview().onDragDropEvent((e) => {
        if (e.payload.type !== "drop" || !e.payload.paths.length) return;
        // A sliced job is not a project. Dropping one opens the Post-Slice
        // Doctor rather than trying to read it as a model.
        const sliced = e.payload.paths.find((p) => /\.gcode$/i.test(p));
        if (sliced) {
          setSliced(sliced);
          nav("/after-slicing");
          return;
        }
        const model = e.payload.paths.find((p) => /\.(stl|3mf)$/i.test(p));
        if (!model) return;
        setFile(model);
        nav(JOB_ROUTE);
      });
      cleanup = () => { un.then((f) => f()); };
    } catch {
      /* not running inside Tauri — drag-drop disabled */
    }
    return () => cleanup?.();
  }, [nav, setFile, setSliced]);

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-background text-foreground">
      <Sidebar className="hidden md:flex" />
      {menuOpen && (
        <div className="fixed inset-0 z-40 md:hidden" role="dialog" aria-modal="true" aria-label="Menu" ref={drawer} onKeyDown={onDrawerKey}>
          <button type="button" tabIndex={-1} aria-label="Close menu" className="absolute inset-0 bg-black/50" onClick={() => closeMenu()} />
          <Sidebar id="nav-drawer" className="relative flex shadow-xl" onNavigate={() => closeMenu(false)} />
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar ref={menuButton} title={titleFor(pathname)} menuOpen={menuOpen} onMenu={() => setMenuOpen((o) => !o)} />
        <main ref={main} tabIndex={-1} className="flex-1 overflow-y-auto outline-none">
          <div className="mx-auto w-full max-w-[1400px] px-4 py-6 sm:px-8 sm:py-8 2xl:px-12">
            <Outlet />
          </div>
        </main>
        <StatusBar />
      </div>
      <Toaster />
    </div>
  );
}
