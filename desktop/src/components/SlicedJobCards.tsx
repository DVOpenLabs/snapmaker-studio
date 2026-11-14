import { PostSliceCard } from "@/components/PostSliceCard";
import { MaterialPlanCard, PrintPlanCard, SendReadyCard } from "@/components/PostSlicePanels";
import { useSliced } from "@/store/sliced";

/**
 * The four checks of an open G-code, read again whenever the file at that path is
 * replaced by a different finished export. Every page that shows them goes through
 * this one place, so none can keep presenting the old bytes' analysis as current.
 */
export function SlicedJobCards({ path, projectPath }: { path: string; projectPath?: string }) {
  const revision = useSliced((s) => s.revision);
  const key = `${path}#${revision}`;
  return (
    <>
      <SendReadyCard key={`send-${key}`} path={path} projectPath={projectPath} />
      <PostSliceCard key={`post-${key}`} path={path} projectPath={projectPath} />
      <MaterialPlanCard key={`mat-${key}`} path={path} />
      <PrintPlanCard key={`plan-${key}`} path={path} />
    </>
  );
}
