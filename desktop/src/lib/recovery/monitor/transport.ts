import { validateMonitoringReply } from "./reply";
import { apiInfo } from "@/api";

function abortable<T>(pending: Promise<T>, signal: AbortSignal): Promise<T> {
  return new Promise((resolve, reject) => {
    const stop = () => reject(new Error("Monitoring stopped or timed out."));
    if (signal.aborted) { void pending.catch(() => undefined); stop(); return; }
    signal.addEventListener("abort", stop, { once: true });
    pending.then(value => { signal.removeEventListener("abort", stop); resolve(value); }, error => { signal.removeEventListener("abort", stop); reject(error); });
  });
}

/** Track-local transport; cancellation never changes shared API callers. */
export async function requestMonitoring<T>(route: "read" | "history", body: { host: string; port: number; previous_state?: string }, signal: AbortSignal): Promise<T> {
  // Manual composition also works on older WebKitGTK without AbortSignal.any/timeout.
  const timeout = new AbortController();
  const combined = new AbortController();
  const stop = () => combined.abort();
  const deadline = setTimeout(() => { timeout.abort(); combined.abort(); }, 4000);
  if (signal.aborted) combined.abort();
  else signal.addEventListener("abort", stop, { once: true });
  const bounded = combined.signal;
  try {
    const info = await abortable(apiInfo(), bounded);
    if (!Number.isInteger(info.port) || info.port < 1 || info.port > 65535 || !info.token) throw new Error("The local Studio service is unavailable.");
    const response = await abortable(fetch(`http://127.0.0.1:${info.port}/monitoring/${route}`, {
      method: "POST", headers: { "Content-Type": "application/json", "X-Auth-Token": info.token },
      body: JSON.stringify(body), signal: bounded,
    }), bounded);
    if (!response.ok) {
      const detail = await abortable(response.json().catch(() => null), bounded);
      const message = detail && typeof detail.message === "string" ? detail.message.trim().slice(0, 512) : "";
      throw new Error(message || `Monitoring ${route === "read" ? "status" : "history"} could not be read (${response.status}).`);
    }
    const value = await abortable(response.json(), bounded);
    return validateMonitoringReply(route, value) as T;
  } catch (cause) {
    if (signal.aborted) throw new Error("Monitoring was stopped.");
    if (timeout.signal.aborted) throw new Error("The monitoring request timed out. Read again when the service is available.");
    throw cause;
  } finally {
    clearTimeout(deadline); signal.removeEventListener("abort", stop);
  }
}
