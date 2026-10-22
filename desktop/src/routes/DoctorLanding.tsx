import { useEffect } from "react";
import { useParams, useNavigate, Navigate, Link } from "react-router-dom";
import { ArrowRight, Plus, Stethoscope, GitCompareArrows } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/layout";
import { doctorById } from "@/lib/doctors";
import { useOpenFile } from "@/hooks/useOpenFile";
import { useSession } from "@/store/session";
import { BusinessDoctors } from "@/components/BusinessDoctors";
import NotFound from "@/routes/NotFound";
import { JOB_ROUTE } from "@/lib/routes";

const BIZ_DOCTORS = new Set(["cost", "pricing", "profit"]);

// Safe landing for the model-based Doctors. The Doctors run on an open model in
// the workspace; this page explains what the Doctor does and routes the user to
// the real functionality (open a model / continue with the current one). It does
// NOT fake a working Doctor — it is an honest entry point.
export default function DoctorLanding() {
  const { id } = useParams();
  const nav = useNavigate();
  const openFile = useOpenFile();
  const file = useSession((s) => s.file);
  const doc = doctorById(id);

  // Project Doctor runs in the workspace on the open model. If a model is already
  // loaded, skip the "open a model" explainer and go straight to the results.
  useEffect(() => {
    if (file && doc?.id === "project") nav("/workspace", { replace: true });
  }, [file, doc?.id, nav]);

  if (!doc) return <NotFound />;
  // /doctor/pricing and /doctor/profit are legacy aliases of the one Cost page —
  // redirect so there is a single canonical URL (beta.21 dedupe).
  if (doc.id === "pricing" || doc.id === "profit") {
    return <Navigate to="/doctor/cost" replace />;
  }
  const Icon = doc.icon;

  // Cost / Pricing / Profit run on the open model — show the real calculator here,
  // not a "how to run" placeholder, when a file is loaded.
  if (file && BIZ_DOCTORS.has(doc.id)) {
    return (
      <div className="space-y-6">
        <PageHeader icon={Icon} title="Cost & Pricing Doctor"
          subtitle="Cost, suggested price, and profit for the open model — one calculator." />
        <Card><CardContent className="space-y-1 p-5">
          <p className="text-sm font-semibold">{file.name}</p>
          <p className="text-xs text-muted-foreground">
            Cost, pricing and profit for the open model — your local assumptions, not financial advice.
          </p>
        </CardContent></Card>
        <BusinessDoctors filePath={file.path} />
        <p className="text-xs text-muted-foreground">
          Want the full design checks too?{" "}
          <Link to="/workspace" className="text-primary hover:underline">Open the workspace</Link>.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader icon={Icon} title={doc.name} subtitle={doc.answers} />

      <Card><CardContent className="space-y-4 p-5">
        <p className="flex items-center gap-2 text-sm font-semibold">
          <Stethoscope className="h-4 w-4 text-primary" /> How to run the {doc.name}
        </p>
        <p className="text-sm text-muted-foreground">
          The {doc.name} runs on a model. Open an STL or 3MF and Studio checks it
          automatically in the workspace — your file stays on your computer.
        </p>

        <div className="flex flex-wrap gap-2">
          <Button size="sm" onClick={openFile}>
            <Plus className="h-4 w-4" /> Open a model
          </Button>
          {file && (
            <Button size="sm" variant="secondary" onClick={() => nav(JOB_ROUTE)}>
              Continue with {file.name} <ArrowRight className="h-4 w-4" />
            </Button>
          )}
        </div>

        {!file && (
          <p className="text-xs text-muted-foreground">
            Open a 3MF or STL to check it for your U1. New here? See the demo on the{" "}
            <Link to="/" className="text-primary hover:underline">Dashboard</Link> to
            see how Studio works — your file stays on your computer.
          </p>
        )}

        {doc.id === "project" && (
          <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <GitCompareArrows className="h-3.5 w-3.5" />
            Foreign or stale 3MF?{" "}
            <Link to="/compatibility" className="text-primary hover:underline">Run the Compatibility Doctor</Link>
          </p>
        )}

        {doc.id === "multi-material" && (
          <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <GitCompareArrows className="h-3.5 w-3.5" />
            Need to fix one plate's colour?{" "}
            <Link to="/colors" className="text-primary hover:underline">Open Colors &amp; Materials</Link>
          </p>
        )}
      </CardContent></Card>
    </div>
  );
}
