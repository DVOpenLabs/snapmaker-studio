import { describe, expect, it } from "vitest";
import { canonicalHost, displayHost } from "./host";

describe("canonicalHost", () => {
  it("trims and lowercases a DNS name", () => {
    expect(canonicalHost("  U1.Local  ")).toEqual({ ok: true, value: "u1.local" });
  });

  it("strips exactly one trailing dot", () => {
    expect(canonicalHost("u1.local.")).toEqual({ ok: true, value: "u1.local" });
  });

  it("rejects an empty address", () => {
    expect(canonicalHost("   ").ok).toBe(false);
  });

  it("rejects embedded whitespace", () => {
    expect(canonicalHost("u1 .local").ok).toBe(false);
  });

  it("rejects a scheme", () => {
    expect(canonicalHost("http://u1.local").ok).toBe(false);
  });

  it("rejects a path", () => {
    expect(canonicalHost("u1.local/status").ok).toBe(false);
  });

  it("rejects an embedded port", () => {
    expect(canonicalHost("u1.local:7125").ok).toBe(false);
  });

  it("brackets and lowercases a bare IPv6 address", () => {
    expect(canonicalHost("FE80::1")).toEqual({ ok: true, value: "[fe80::1]" });
  });

  it("lowercases an already-bracketed IPv6 address", () => {
    expect(canonicalHost("[FE80::1]")).toEqual({ ok: true, value: "[fe80::1]" });
  });

  it("rejects a bracketed address with a trailing port", () => {
    expect(canonicalHost("[fe80::1]:7125").ok).toBe(false);
  });

  it("is case-insensitive for the same DNS host", () => {
    const a = canonicalHost("U1.local");
    const b = canonicalHost("u1.LOCAL");
    expect(a.ok && b.ok && a.value === b.value).toBe(true);
  });
});

describe("canonicalHost IPv6 (R2-D1: RFC 5952, matches Python ipaddress)", () => {
  const cases: [string, string][] = [
    ["[2001:0db8::1]", "[2001:db8::1]"],
    ["[2001:db8:0:0:0:0:0:1]", "[2001:db8::1]"],
    ["2001:DB8::0:1", "[2001:db8::1]"],
    ["[::1]", "[::1]"],
    ["[fe80::0:0:1]", "[fe80::1]"],
  ];

  it.each(cases)("canonicalises %s to the RFC 5952 compressed form %s", (input, expected) => {
    expect(canonicalHost(input)).toEqual({ ok: true, value: expected });
  });

  it("compresses the leftmost run on a tie between equal-length zero runs", () => {
    // 2001:0:0:1:0:0:0:1 -> two zero runs of length 2 and 3; RFC 5952 takes
    // the LONGEST (the run of 3), and only falls back to leftmost on an
    // actual tie. Cross-check with a genuine tie: 1:0:0:1:0:0:1:1.
    expect(canonicalHost("1:0:0:1:0:0:1:1")).toEqual({ ok: true, value: "[1::1:0:0:1:1]" });
  });
});

describe("displayHost", () => {
  it("shows the canonical form for a valid address", () => {
    expect(displayHost(" U1.Local. ")).toBe("u1.local");
  });

  it("falls back to the raw trimmed text while still being typed", () => {
    expect(displayHost("http://")).toBe("http://");
  });
});
