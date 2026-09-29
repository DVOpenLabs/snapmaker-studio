import type { ProviderStatus } from "@/api";

export default function ProviderStatusNote({ status }: { status?: ProviderStatus | null }) {
  if (!status || status.available) return null;
  const errorText = status.error?.trim();
  const reason = errorText
    ? errorText.endsWith(".") ? errorText : `${errorText}.`
    : `${status.name} did not answer.`;
  return (
    <p className="rounded-md border border-border p-2.5 text-xs text-muted-foreground">
      Studio could not read {status.name}: {reason} Spool weights from {status.name} are unknown until it answers.
    </p>
  );
}
