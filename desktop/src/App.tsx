import { useEffect } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AppShell } from "@/components/shell/AppShell";
import AfterSlicing from "@/routes/AfterSlicing";
import Cockpit from "@/routes/Cockpit";
import Dashboard from "@/routes/Dashboard";
import Projects from "@/routes/Projects";
import Batch from "@/routes/Batch";
import WorkspaceSwitch from "@/routes/WorkspaceSwitch";
import Printers from "@/routes/Printers";
import Settings from "@/routes/Settings";
import WhyStudio from "@/routes/WhyStudio";
import PlateRemap from "@/routes/PlateRemap";
import DoctorLanding from "@/routes/DoctorLanding";
import FindModels from "@/routes/FindModels";
import SourceCompatibility from "@/routes/SourceCompatibility";
import ScaleDoctor from "@/routes/ScaleDoctor";
import FirstLayer from "@/routes/FirstLayer";
import CompatibilityHub from "@/routes/CompatibilityHub";
import PrintQualityHub from "@/routes/PrintQualityHub";
import ColorsMaterials from "@/routes/ColorsMaterials";
import BeginnerWorkflow from "@/routes/BeginnerWorkflow";
import Help from "@/routes/Help";
import NotFound from "@/routes/NotFound";
import { useTheme } from "@/store/theme";
import { useSession } from "@/store/session";
import { launchFile, maybeAutoCheckUpdate } from "@/api";
import { useSliced } from "@/store/sliced";
import { useUpdateCheckStore } from "@/store/updateCheck";
import { useToast } from "@/store/toast";

const queryClient = new QueryClient();

export default function App() {
  const { theme } = useTheme();

  // Keep the <html> class in sync with the persisted theme on load.
  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
  }, [theme]);

  // A model handed to Studio on the command line — a file association, "Open
  // with", or an automated run — should be open when the window appears, rather
  // than making the user find it again through the picker.
  const setFile = useSession((s) => s.setFile);
  useEffect(() => {
    let alive = true;
    launchFile().then((path) => {
      if (!alive || !path) return;
      // A sliced job is not a project. Studio now accepts .gcode on the command
      // line too, and that has to land in the Post-Slice Doctor.
      if (/\.gcode$/i.test(path)) {
        useSliced.getState().setSliced(path);
        return;
      }
      setFile(path);
    });
    return () => {
      alive = false;
    };
  }, [setFile]);

  // The opt-in automatic update check (Settings/Help → "Automatically check
  // for updates") — once per launch, here rather than on the Help page
  // itself, so it genuinely runs regardless of which page someone opens
  // first. `maybeAutoCheckUpdate` is itself the gate: it silently does
  // nothing unless the preference is on AND at least a day has passed since
  // the last attempt, so calling it unconditionally on every launch is safe.
  useEffect(() => {
    let alive = true;
    maybeAutoCheckUpdate()
      .then((info) => {
        if (!alive || !info) return;
        useUpdateCheckStore.getState().setAutoResult(info);
        if (info.newer) {
          useToast.getState().show(`Snapmaker Studio ${info.latest} is available — see Help.`);
        }
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/projects" element={<Projects />} />
            <Route path="/batch" element={<Batch />} />
            <Route path="/workspace" element={<WorkspaceSwitch />} />
            <Route path="/printers" element={<Printers />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/why" element={<WhyStudio />} />
            <Route path="/help" element={<Help />} />
            <Route path="/plate-remap" element={<PlateRemap />} />
            <Route path="/compatibility" element={<CompatibilityHub />} />
            <Route path="/after-slicing" element={<AfterSlicing />} />
            <Route path="/this-print" element={<Cockpit />} />
            <Route path="/find-models" element={<FindModels />} />
            <Route path="/source" element={<SourceCompatibility />} />
            <Route path="/scale" element={<ScaleDoctor />} />
            <Route path="/print-quality" element={<PrintQualityHub />} />
            <Route path="/colors" element={<ColorsMaterials />} />
            <Route path="/first-layer" element={<FirstLayer />} />
            <Route path="/start" element={<BeginnerWorkflow />} />
            <Route path="/doctor/:id" element={<DoctorLanding />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
