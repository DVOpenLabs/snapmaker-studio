import { ShieldCheck, FileSearch } from "lucide-react";
import { ToolTabs } from "@/components/ui/ToolTabs";
import Compatibility from "@/routes/Compatibility";
import SourceCompatibility from "@/routes/SourceCompatibility";

// Merged "Compatibility" page: the Compatibility Doctor and the Source Check both
// answer "can this foreign file work on the U1?", so they share one sidebar item
// as two tabs. /source still resolves on its own for any deep links.
export default function CompatibilityHub() {
  return (
    <ToolTabs label="Compatibility tools" tabs={[
      { id: "compatibility", label: "Compatibility", icon: ShieldCheck, el: <Compatibility /> },
      { id: "source", label: "Source Check", icon: FileSearch, el: <SourceCompatibility /> },
    ]} />
  );
}
