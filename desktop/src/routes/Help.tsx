import { Link } from "react-router-dom";
import { BookOpen, ArrowRight, ExternalLink } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/layout";
import { PRIMARY_DOCTORS } from "@/lib/doctors";
import { SupportBundle } from "@/components/SupportBundle";
import { UpdateCheck } from "@/components/UpdateCheck";
import { USER_GUIDE_BLURB, USER_GUIDE_LABEL, USER_GUIDE_URL } from "@/lib/guide";

// Lightweight help/about hub. Honest pointers only — links to in-app surfaces
// that actually exist; no fabricated documentation.
export default function Help() {
  return (
    <div className="space-y-6">
      <PageHeader icon={BookOpen} title="Docs / Help"
        subtitle="What Snapmaker Studio does and where to find each tool." />

      <Card><CardContent className="space-y-2 p-5 text-sm">
        <p className="font-semibold">New here? Follow the guide</p>
        <p className="text-muted-foreground">{USER_GUIDE_BLURB}</p>
        <a href={USER_GUIDE_URL} target="_blank" rel="noreferrer"
          className="inline-flex items-center gap-1 text-primary hover:underline">
          {USER_GUIDE_LABEL} <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
        </a>
      </CardContent></Card>

      <Card><CardContent className="space-y-3 p-5 text-sm">
        <p className="font-semibold">The Intelligence Layer for Open 3D Printing</p>
        <p className="text-muted-foreground">
          Orca slices. Fluidd monitors. Studio helps decide what to fix before you
          print. Studio checks a model and your U1 before a layer is sliced —
          local-first, nothing leaves your network.
        </p>
        <Link to="/why" className="inline-flex items-center gap-1 text-primary hover:underline">
          Why Studio? <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      </CardContent></Card>

      <Card><CardContent className="space-y-2 p-5">
        <p className="text-sm font-semibold">The Doctors</p>
        <ul className="space-y-1 text-sm">
          {PRIMARY_DOCTORS.map((d) => (
            <li key={d.id}>
              <Link to={d.route} className="text-primary hover:underline">{d.name}</Link>
              <span className="text-muted-foreground"> — {d.answers}</span>
            </li>
          ))}
        </ul>
        <p className="text-[11px] text-muted-foreground">
          The model-based Doctors run on an open model in the workspace — open a model, and they check it automatically.
        </p>
      </CardContent></Card>

      <Card><CardContent className="space-y-2 p-5">
        <p className="text-sm font-semibold">Fix &amp; diagnose tools — when to use each</p>
        <ul className="space-y-1.5 text-sm">
          <li>
            <Link to="/compatibility" className="text-primary hover:underline">Compatibility</Link>
            <span className="text-muted-foreground"> — <b>before slicing</b>: a 3MF won't open cleanly or carries foreign/stale settings. Next: open the 3MF; read-only, no auto-fix.</span>
          </li>
          <li>
            <Link to="/print-quality" className="text-primary hover:underline">Print Quality Doctor</Link>
            <span className="text-muted-foreground"> — <b>after a bad print/preview</b>: pick the symptom for likely causes + safe first checks. Advisory only.</span>
          </li>
          <li>
            <Link to="/scale" className="text-primary hover:underline">Scale Doctor</Link>
            <span className="text-muted-foreground"> — <b>before resizing</b>: preview U1 fit and material/cost of a uniform scale. Analysis-only; no file changes.</span>
          </li>
          <li>
            <Link to="/colors" className="text-primary hover:underline">Colors &amp; Materials</Link>
            <span className="text-muted-foreground"> — check toolhead/colour mapping, or change one plate's colour safely; writes a verified copy, original untouched.</span>
          </li>
          <li>
            <Link to="/find-models" className="text-primary hover:underline">Find Models</Link>
            <span className="text-muted-foreground"> — browse approved model sites inside Studio and download with the site's own button; Studio adds supported downloads to your Library. Check the license before you use a model.</span>
          </li>
        </ul>
      </CardContent></Card>
          <UpdateCheck />
      <SupportBundle />
    </div>
  );
}
