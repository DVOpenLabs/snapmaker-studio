# SpoolEase — the wire protocol Studio reads

**Status: PROTOCOL VERIFIED against source and fixtures; REAL SPOOLEASE DEVICE
VALIDATION PENDING.** Everything below was read out of SpoolEase's own source
code and proved against fixtures built from it, and against a local HTTP
server that speaks the same bytes. Nobody has yet run Studio against a real,
physical SpoolEase device. Until that happens, treat this integration as
carefully reasoned from the source rather than field-tested.

## What was inspected

- **SpoolEase** — commit `3532f8d962dd1a95c7d4ebb37beddca5bbefd39a`.
- **esp-hal-app-framework** (the web-app/encryption layer SpoolEase is built
  on) — version `0.6.1`, commit `43daad9d1795b21a7f4ea3ef610b328cabbfeda1`.

Both are upstream, third-party projects. Studio reads their public HTTP API;
it does not vendor, modify or redistribute their code.

## Read-only, one endpoint

Studio calls exactly one route: `GET {your SpoolEase address}/api/spools`,
`Accept: text/plain`, no body, no cookies, no credentials. Studio adds no
header beyond `Accept`; Python's standard HTTP client (`urllib`) adds its own
usual headers on top of that (`Host`, `User-Agent`, `Accept-Encoding:
identity`, `Connection: close`). It never calls anything else SpoolEase
exposes — no write, no configuration, no upload.

## The security key

SpoolEase encrypts its spool list with a key you set in its own settings (or
a random one it shows on its screen if you have not set a fixed one — it
changes on every SpoolEase restart until you do). Studio asks for that key in
**Settings → Materials provider** and keeps it in memory for the running
session only: never written to Studio's library database, its settings file,
a URL, a log, or a diagnostics bundle. Restart Studio and you enter it again.

Before use, the typed key is trimmed of leading/trailing whitespace using the
same rule a JavaScript `String.prototype.trim()` call uses — this matches
SpoolEase's own reference config page, which trims a key before using it to
decrypt. A key that is only whitespace, or empty, is treated as no key at all
and nothing is sent to the network. There is no length limit.

## Key derivation and framing

1. The typed key (UTF-8 bytes, after trimming) is run through
   **PBKDF2-HMAC-SHA256**, salt `example_salt` (SpoolEase's own hard-coded
   salt — not a Studio secret), 10 000 iterations, 32-byte output. This
   derived key is computed fresh for every request and kept nowhere after the
   request finishes.
2. SpoolEase's response body is ASCII text: the first 16 characters are a
   12-byte nonce, standard-alphabet base64, no padding; everything after that
   is the ciphertext followed by a 16-byte AES-GCM authentication tag, same
   encoding.
3. Studio decrypts with **AES-256-GCM** (no additional authenticated data)
   using the derived key and that nonce. A wrong key or a damaged response
   both fail the same way — AES-GCM cannot and should not distinguish them —
   and Studio reports "the security key is wrong or the response was
   damaged."

## The spool list (CSV, no header)

The decrypted plaintext is one line per spool, comma-separated, RFC4180-style
quoting (a field containing a comma, a quote or a newline is wrapped in
double quotes; an embedded quote is doubled), no header row. Columns, in
order:

```
id, tag_id, material_type, material_subtype, color_name, color_code, note,
brand, weight_advertised, weight_core, weight_new, weight_current,
slicer_filament, added_time, encode_time, added_full, consumed_since_add,
consumed_since_weight, ext_has_k, data_origin, tag_type
```

The first 12 columns are always present. Columns 13–21 default to empty on an
older SpoolEase's shorter row. An empty plaintext (an encrypted empty list) is
a successful read with zero spools, not an error.

### Field codecs

- **Integers** (`weight_advertised`, `weight_core`, `weight_new`,
  `weight_current`, `added_time`, `encode_time`): empty means "not set";
  otherwise a plain ASCII integer within the 32-bit signed range. `added_time`
  is a Unix timestamp and is shown as an ISO-8601 UTC date.
- **Flags** (`added_full`, `ext_has_k`): `y`/`Y` for true, `n`/`N` for false,
  empty for "not set".
- **Consumption counters** (`consumed_since_add`, `consumed_since_weight`):
  empty means zero; otherwise exactly 6 characters of canonical base64
  decoding to a little-endian 32-bit float. A value that will not decode, or
  a negative one, marks that spool's remaining weight unknown — it does not
  fail the whole read.

Anything else — the wrong number of columns, an empty or duplicated spool id,
an unreadable integer or flag — fails the whole read with a message asking
you to check your SpoolEase's address, or that it may need a Studio update.

## How much filament is left — always an estimate

SpoolEase weighs a spool on its own scale and separately counts what a
**Bambu** print has consumed since. It has no way to see anything a Snapmaker
U1 has printed. So every remaining-weight figure Studio computes from a
SpoolEase spool is **DERIVED** — arithmetic Studio performed, never a
figure SpoolEase itself calls settled — and it always carries this note:

> SpoolEase does not record when this spool was weighed and cannot see what
> your U1 has used since, so treat this as an estimate.

Two ways Studio arrives at a number, depending on what the spool row has:

- **`weight_core` known:** `remaining = weight_current − weight_core −
  consumed_since_weight`.
- **`weight_core` unknown, but `weight_new` and `weight_advertised` are
  both present:** Studio estimates the core weight as
  `weight_new − weight_advertised`, then applies the same subtraction.
- **Neither:** unknown. Studio says so and does not guess.

A DERIVED, undated figure never blocks a send by itself — it can only warn.
See [`../MATERIAL_PROVIDERS.md`](../MATERIAL_PROVIDERS.md) for how that fits
alongside Spoolman and Bambuddy.

## Slot mapping

Like Spoolman and Bambuddy, SpoolEase does not know which printer slot a
spool is loaded into — you tell Studio that in Settings, the same way as for
the other two providers. SpoolEase spool ids are decimal strings; Studio
compares slot-map entries as text on both sides, so an existing numeric
mapping (from Spoolman or Bambuddy) still works unchanged if you switch
providers, and a SpoolEase mapping works the same way back.

## Network behaviour (shared with every provider)

- **Local network only.** Studio only ever connects to an address it
  resolves to something on your own network — loopback, a private range, a
  link-local address, a Tailscale-style carrier-grade-NAT address, or an
  IPv6 site-local address. A name that resolves to a mix of local and public
  addresses is read on the local address only; a name that resolves only to
  a public address is refused with a message telling you to enter the
  provider's own local address instead (for example its `192.168.x.x`
  address).
- **No proxies.** Environment- and system-configured proxies are ignored for
  a provider read — Studio connects to your SpoolEase directly.
- **Redirects.** A redirect that stays on your own network is followed; one
  that leaves it is refused.
- **Scoped IPv6 literals** (`fe80::1%eth0`, `fe80::1%12`) are passed to the
  operating system exactly as Python's standard networking library does.
  Studio adds no translation of its own. On Windows, only the numeric
  interface-index form (`%12`) is known to resolve; a named zone
  (`%eth0`) is a platform limitation, not something this integration
  changes.

### Limits — what is bounded, and what honestly is not

One deadline (4 seconds by default) is shared across every connection
attempt Studio makes for one read — every address a name resolves to, and
every redirect hop. A device with several local addresses shares that
budget between them, rather than each one getting the whole allowance in
turn.

DNS lookups are **not** bounded by that deadline — this is unchanged from
every provider Studio has ever read, and identical to what the underlying
Python networking library has always done. The shared deadline bounds
connection attempts only (every address a name resolves to, every redirect
hop). Once a connection is made, each individual read — the status line,
the response headers, the body — reverts to the connection's own base
per-read timeout (the same 4-second default, not whatever happened to be
left of the shared deadline at that point), exactly as reading from
Spoolman or Bambuddy always has. That per-read timeout is **not** a
wall-clock bound on the whole exchange: a device that trickles bytes very
slowly can still hold the status line, the headers, and the body each open
for close to the full per-read allowance in turn, so a very slow drip can
in principle hold a request open considerably longer than the deadline
alone suggests. This is the same class of limit every provider read has
always had, is not new here, and is tracked as follow-up work (a
whole-exchange deadline) rather than fixed in this change.

The response body itself is capped at 4 MB; anything larger is refused
before it is fully read.

## Errors, in the order Studio checks them

| Condition | What Studio says |
|---|---|
| The address is not on your network, or resolves/redirects off it | Says which address, and that Studio only reads providers on your own network |
| No key entered | Asks for the key in Settings |
| The key has characters Studio cannot use | Asks you to copy it exactly as SpoolEase shows it |
| This build cannot decrypt (a packaging problem) | Asks you to report it |
| SpoolEase returned an HTTP error status | Names the status code |
| SpoolEase did not answer within the timeout | Names roughly how long Studio waited |
| The connection failed, was refused, reset, or the name did not resolve | Names what went wrong (never how long Studio waited — nothing timed out) |
| The response was larger than Studio will read from a provider | Says so, without repeating any of it |
| The response was empty | Suggests giving SpoolEase a moment and trying again |
| The response could not be parsed as SpoolEase's wire format | Suggests checking the address points at a SpoolEase device |
| The key was wrong, or the response was damaged | Asks you to check the key shown on the SpoolEase screen |
| The decrypted text was not valid text | Says Studio could not read it as text |
| The spool list itself is in a form Studio does not recognise | Suggests Studio may need an update for this SpoolEase version |

None of these messages ever contain the security key, the key Studio derives
from it, or the raw response body.

**A note on error precision going forward:** today, an address problem on
any provider reports the same `invalid_address` reason regardless of which
provider it is; every other SpoolEase failure carries a specific reason of
its own, while Spoolman and Bambuddy currently report only "reachable" or
"not reachable" for their own network failures. Giving Spoolman and
Bambuddy the same granularity SpoolEase has is recorded as follow-up work,
not a behaviour change made here.

## Downgrading

If you go back to a Studio version older than the one that added SpoolEase,
choose **None** (or another provider) in Settings before doing so — an old
version does not know the `spoolease` provider kind and will not open your
saved settings correctly if it is still selected.
