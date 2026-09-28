import type { ProviderStatus } from "@/api";

export default function ProviderStatusNote({ status }: { status?: ProviderStatus | null }) {
  if (!status || status.available) return null;
  return (
    <p className="rounded-md border border-border p-2.5 text-xs text-muted-foreground">
      Studio could not read {status.name}: {status.error} Spool weights from {status.name} are unknown until it answers.
    </p>
  );
}
