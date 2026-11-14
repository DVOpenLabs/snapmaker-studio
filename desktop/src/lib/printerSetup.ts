// Pure helpers for "has the person set up a printer?". No storage, no network.
// Not set up (no address) is a different state from set up but unreachable
// (an address that did not answer): only the second one is ever looked up.

/** Trim an address; anything blank means "not set up". */
export function normalizeHost(h: string | null | undefined): string {
  return (h ?? "").trim();
}

/** A stored value from an earlier version: kept as is when non-blank, otherwise not set up. */
export function hostFromStorage(stored: string | null): string {
  return normalizeHost(stored);
}

export function isPrinterSetUp(host: string | null | undefined): boolean {
  return normalizeHost(host) !== "";
}

/** Thrown by the printer API calls when there is no address, before any request is made. */
export class PrinterNotSetUpError extends Error {
  constructor() {
    super("No printer is set up yet. Add your printer's address in Settings or the Printer Hub first.");
    this.name = "PrinterNotSetUpError";
  }
}

/** The trimmed address, or a thrown PrinterNotSetUpError. Call before building any printer request. */
export function requirePrinterHost(host: string | null | undefined): string {
  const h = normalizeHost(host);
  if (!h) throw new PrinterNotSetUpError();
  return h;
}
