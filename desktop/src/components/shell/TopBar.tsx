import { forwardRef } from "react";
import { Search, Sun, Moon, FolderOpen, Menu } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { useTheme } from "@/store/theme";
import { useOpenFile } from "@/hooks/useOpenFile";

export const TopBar = forwardRef<HTMLButtonElement, { title: string; menuOpen?: boolean; onMenu?: () => void }>(function TopBar({ title, menuOpen = false, onMenu }, menuRef) {
  const { theme, toggle } = useTheme();
  const openFile = useOpenFile();
  const nav = useNavigate();
  return (
    <header className="flex h-14 items-center gap-3 border-b border-border bg-background px-4">
      {onMenu && (
        <Button ref={menuRef} variant="ghost" size="icon" className="md:hidden" onClick={onMenu}
                aria-label="Menu" aria-expanded={menuOpen} aria-controls={menuOpen ? "nav-drawer" : undefined}>
          <Menu className="h-4 w-4" aria-hidden="true" />
        </Button>
      )}
      <h1 className="min-w-0 truncate text-sm font-medium text-muted-foreground">{title}</h1>
      <div className="ml-auto flex items-center gap-2">
        <button onClick={() => nav("/projects")} className="flex h-9 items-center gap-2 rounded-md border border-border bg-card px-3 text-sm text-muted-foreground hover:bg-muted">
          <Search className="h-4 w-4" />
          <span className="hidden sm:inline">Find a design…</span>
        </button>
        <Button variant="secondary" size="sm" onClick={openFile}>
          <FolderOpen className="h-4 w-4" /> Open
        </Button>
        <Button variant="ghost" size="icon" onClick={toggle} aria-label="Toggle theme">
          {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </Button>
      </div>
    </header>
  );
});
