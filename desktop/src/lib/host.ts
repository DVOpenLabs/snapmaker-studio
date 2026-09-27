// Canonical printer-address display, matching the backend's canonical_host()
// (which wraps Python's `ipaddress` module for IPv6) closely enough for
// consistent presentation (v1.2 plan A1.2). Display-only as of the round-3
// re-diagnosis (F1): this used to also key a client-side revision floor, but
// that floor was deleted (see store/nozzleRevision.ts) after repeated review
// rounds found races in it — freshness is now a per-component request token
// plus a single unkeyed global "something changed" counter, neither of which
// needs a canonical host at all. The backend remains the sole source of
// truth for storage keys and validation; this module never decides what to
// send to the engine — the raw host the user typed is always sent, and the
// backend canonicalises it.

export type CanonicalHost = { ok: true; value: string } | { ok: false; error: string };

const INVALID = "That printer address isn't valid.";

/** Parses a bracket-free IPv6 address into 8 sixteen-bit groups (0..65535),
 *  expanding a single "::" run. Returns null for anything that isn't a valid
 *  IPv6 literal (mixed IPv4-in-IPv6 notation is not supported — unused by
 *  this app and rejected as invalid). */
function expandIPv6(input: string): number[] | null {
  if (input === "") return null;
  const doubleColonCount = (input.match(/::/g) ?? []).length;
  if (doubleColonCount > 1) return null;

  let head: string[];
  let tail: string[];
  if (doubleColonCount === 1) {
    const [before, after] = input.split("::");
    head = before === "" ? [] : before.split(":");
    tail = after === "" ? [] : after.split(":");
  } else {
    head = input.split(":");
    tail = [];
  }

  const missing = 8 - (head.length + tail.length);
  if (missing < 0) return null;
  if (doubleColonCount === 0 && missing !== 0) return null; // no "::" must have exactly 8 groups
  if (doubleColonCount === 1 && missing < 1) return null; // "::" must stand for >=1 group

  const zeros = new Array(missing).fill("0");
  const full = [...head, ...zeros, ...tail];
  if (full.length !== 8) return null;

  const groups: number[] = [];
  for (const g of full) {
    if (!/^[0-9a-fA-F]{1,4}$/.test(g)) return null;
    groups.push(parseInt(g, 16));
  }
  return groups;
}

/** RFC 5952 §4: lowercase, no leading zeros, and the *longest* run of two or
 *  more consecutive all-zero groups compressed to "::" (leftmost run wins a
 *  tie); no compression at all when no run reaches length 2. Matches what
 *  Python's `ipaddress.IPv6Address(...).compressed` produces. */
function compressIPv6(groups: number[]): string {
  let bestStart = -1;
  let bestLen = 0;
  let curStart = -1;
  let curLen = 0;
  for (let i = 0; i < groups.length; i += 1) {
    if (groups[i] === 0) {
      if (curStart === -1) curStart = i;
      curLen += 1;
    } else {
      if (curLen > bestLen) { bestLen = curLen; bestStart = curStart; }
      curStart = -1;
      curLen = 0;
    }
  }
  if (curLen > bestLen) { bestLen = curLen; bestStart = curStart; }

  const hex = (n: number) => n.toString(16);
  if (bestLen >= 2) {
    const before = groups.slice(0, bestStart).map(hex);
    const after = groups.slice(bestStart + bestLen).map(hex);
    return `${before.join(":")}::${after.join(":")}`;
  }
  return groups.map(hex).join(":");
}

/** Bracket-free input in, RFC 5952 compressed form out, or null if not a
 *  valid IPv6 literal. */
function canonicalIPv6(input: string): string | null {
  const groups = expandIPv6(input);
  return groups ? compressIPv6(groups) : null;
}

/** Mirrors A1.2/canonical_host(): trim; reject embedded whitespace/scheme/
 *  path/port; lowercase DNS names; strip exactly one trailing dot; IPv6
 *  parsed, expanded and RFC-5952-recompressed (matching Python's `ipaddress`),
 *  bracketed. */
export function canonicalHost(raw: string): CanonicalHost {
  const trimmed = raw.trim();
  if (!trimmed) return { ok: false, error: INVALID };
  if (/\s/.test(trimmed)) return { ok: false, error: INVALID };
  if (/^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//.test(trimmed)) return { ok: false, error: INVALID };
  if (trimmed.includes("/")) return { ok: false, error: INVALID };

  if (trimmed.startsWith("[")) {
    const close = trimmed.indexOf("]");
    if (close === -1) return { ok: false, error: INVALID };
    const inner = trimmed.slice(1, close);
    const rest = trimmed.slice(close + 1);
    if (rest) return { ok: false, error: INVALID }; // embedded port belongs in the port field
    const compressed = canonicalIPv6(inner);
    if (compressed === null) return { ok: false, error: INVALID };
    return { ok: true, value: `[${compressed}]` };
  }

  if (trimmed.split(":").length > 2) {
    // Two or more colons with no brackets: only valid as a bare IPv6 address.
    const compressed = canonicalIPv6(trimmed);
    if (compressed === null) return { ok: false, error: INVALID };
    return { ok: true, value: `[${compressed}]` };
  }

  if (trimmed.includes(":")) return { ok: false, error: INVALID }; // embedded host:port

  let value = trimmed.toLowerCase();
  if (value.length > 1 && value.endsWith(".") && !value.endsWith("..")) {
    value = value.slice(0, -1);
  }
  return { ok: true, value };
}

/** What to show next to "for <host>" copy: the canonical form when valid, the
 *  raw text otherwise (so a still-being-typed address never disappears). */
export function displayHost(raw: string): string {
  const c = canonicalHost(raw);
  return c.ok ? c.value : raw.trim();
}
