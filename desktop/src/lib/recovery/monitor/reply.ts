import type { HistoryRead, MonitoringRead } from "../api";
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const text = (value: unknown): value is string => typeof value === "string";
const optionalText = (value: unknown) => value == null || text(value);

/** Validate every nested field the monitoring panel renders before accepting a reply.
 * Unknown status strings remain unknown; optional fields may be absent. No state is inferred. */
export function validateMonitoringReply(route: "read" | "history", value: unknown): MonitoringRead | HistoryRead {
  const refuse = () => { throw new Error(`The monitoring ${route === "read" ? "status" : "history"} reply was not usable. Read again when the local service is available.`); };
  if (!object(value) || !text(value.status)) return refuse();
  if (!optionalText(value.note) || !optionalText(value.association)) return refuse();
  if (route === "read") {
    if (!optionalText(value.filename) || !optionalText(value.print_state) || (value.status === "ok" && !text(value.print_state))) return refuse();
    if (value.camera != null && (!object(value.camera) || !text(value.camera.state))) return refuse();
    if (value.reconciliation != null) {
      const reconciliation = value.reconciliation;
      if (!object(reconciliation) || !text(reconciliation.state) || !text(reconciliation.source) || !Array.isArray(reconciliation.events) || reconciliation.events.length > 32 ||
        !reconciliation.events.every(event => object(event) && text(event.kind) && text(event.from) && text(event.to))) return refuse();
    }
    return value as MonitoringRead;
  }
  if (value.status === "ok" || value.last_job != null) {
    if (value.last_job !== null && (!object(value.last_job) || !text(value.last_job.outcome) || !optionalText(value.last_job.filename))) return refuse();
  }
  return value as HistoryRead;
}
