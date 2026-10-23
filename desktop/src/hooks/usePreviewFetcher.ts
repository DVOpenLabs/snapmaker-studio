import { useCallback, useRef } from "react";
import { paintedPreview } from "@/api";
import type { PaintedPreview } from "@/lib/paintedPreview";

/**
 * The preview reader for one open project. The open file does not change while the project is open (the job screen
 * restarts for another), so its preview is read once and reused when the person flips between the model, the copy
 * and the slice. Any other path is read every time: a copy written again under the same name can hold other colours.
 */
export function usePreviewFetcher(projectPath: string, read: (p: string) => Promise<PaintedPreview> = paintedPreview) {
  const kept = useRef<{ path: string; promise: Promise<PaintedPreview> } | null>(null);
  return useCallback((path: string) => {
    if (path !== projectPath) return read(path);
    if (kept.current?.path !== path) {
      const entry = { path, promise: read(path) };
      kept.current = entry;
      entry.promise.catch(() => { if (kept.current === entry) kept.current = null; });
    }
    return kept.current.promise;
  }, [projectPath, read]);
}
