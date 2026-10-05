import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { listenModelDownloads, registerDownloadedModel } from "@/api";
import { useModelDownloads } from "@/store/modelDownloads";
import { useToast } from "@/store/toast";
import {
  failureMessage, isRegistered, refusalMessage, toAddedItem, type ModelDownloadEvent,
} from "@/lib/modelDownloads";

/** Headless: registers what the Model Browser downloaded into the library, wherever the user is in the app. */
export function ModelDownloadListener() {
  const qc = useQueryClient();

  useEffect(() => {
    let alive = true;
    let off: () => void = () => {};

    async function onFinished(e: ModelDownloadEvent) {
      const store = useModelDownloads.getState();
      try {
        const r = await registerDownloadedModel(e.path, e.site, e.page_url);
        if (!isRegistered(r)) {
          store.setFailure(failureMessage(r?.message || r?.error));
          return;
        }
        const item = toAddedItem(e.path, r);
        store.add(item);
        useToast.getState().show(`${item.heading} — ${item.name}`);
        void qc.invalidateQueries({ queryKey: ["library"] });
      } catch (err) {
        // Only the engine's own message; never the path or anything from the site.
        store.setFailure(failureMessage(err instanceof Error ? err.message : undefined));
      }
    }

    listenModelDownloads({
      onFinished: (e) => { void onFinished(e); },
      onRefused: (e) => useModelDownloads.getState().setRefusal(refusalMessage(e.filename)),
    }).then((un) => { if (alive) off = un; else un(); }).catch(() => {});

    return () => { alive = false; off(); };
  }, [qc]);

  return null;
}
