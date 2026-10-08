import { Stethoscope, Layers } from "lucide-react";
import { ToolTabs } from "@/components/ui/ToolTabs";
import PrintQuality from "@/routes/PrintQuality";
import FirstLayer from "@/routes/FirstLayer";

// Merged "Print Quality" page: first-layer adhesion is a print-quality subtopic, so
// the Print Quality Doctor and First Layer Doctor share one sidebar item as two
// tabs. /first-layer still resolves on its own for any deep links.
export default function PrintQualityHub() {
  return (
    <ToolTabs label="Print quality tools" tabs={[
      { id: "quality", label: "Print Quality", icon: Stethoscope, el: <PrintQuality /> },
      { id: "first-layer", label: "First Layer", icon: Layers, el: <FirstLayer /> },
    ]} />
  );
}
