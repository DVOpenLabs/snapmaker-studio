import { Component, Suspense, lazy, type ReactNode } from "react";
import { Card, CardContent } from "@/components/ui/card";

// The viewer (three.js and the vendored viewport) loads only when this section first renders, so it is not in the
// main bundle.
const ProjectScenePanel = lazy(() => import("./ProjectScenePanel"));

class LoadBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <Card><CardContent className="p-4 text-sm text-muted-foreground" role="alert">
        The 3D view could not be loaded. The rest of this page still works.
      </CardContent></Card>
    );
  }
}

/** Mount point used by the project pages. */
export function ProjectSceneSection({ path, wide = false }: { path: string; wide?: boolean }) {
  return (
    <LoadBoundary>
      <Suspense fallback={<Card><CardContent className="p-4 text-sm text-muted-foreground" role="status">Loading the 3D view</CardContent></Card>}>
        <ProjectScenePanel path={path} wide={wide} />
      </Suspense>
    </LoadBoundary>
  );
}
