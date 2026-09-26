# Which printers Studio understands, and how well

> **State:** this describes `main` after v0.7.2. The published installer,
> v0.7.2, does not contain it. Nothing here is a release announcement.

Studio's printer intelligence talks to Moonraker, the API server that sits in
front of Klipper. That is an open stack, and the checks Studio runs — how many
tools does this machine have, how big is its bed, which firmware features does it
list, what does it say is loaded — are questions any Moonraker printer can be
asked.

Being *able* to ask is not the same as having asked. This page separates the two,
because the difference is the only thing that makes either claim worth reading.

## Verification levels

Every printer Studio ships a profile for carries one of these, and the level is a
statement about evidence rather than about quality.

| Level | What it means |
|---|---|
| **Hardware verified** | A physical machine of this kind was connected and answered these questions, read-only, and the session was recorded. |
| **Profile verified — hardware not tested by this project** | The facts come from the machine's published configuration and have been run through Studio's real printer logic. No machine of this kind has been connected to Studio. |
| **Simulated** | Behaviour exercised only through responses Studio generated for itself. |
| **Not established** | Studio has not determined this. |

There is deliberately no level called "supported". A single word that covers both
of the first two rows would hide exactly the distinction this page exists to make.

## The printers

| Printer | Tools | Build volume | Level | Evidence |
|---|---|---|---|---|
| **Snapmaker U1** | 4 | 270 × 270 × 270 mm printable | **Hardware verified** | A read-only session against a physical U1 on Moonraker port 7125. Recorded as 26/26 in [`internal/evidence/0.7.2.json`](internal/evidence/0.7.2.json); the full report is [`internal/hardware-0.7.2.json`](internal/hardware-0.7.2.json). |
| **VORON 2.4 (250 mm)** | 1 | 250 × 250 × 250 mm | **Profile verified — hardware not tested by this project** | Klipper's own published configuration for the machine, `config/kit-voron2-250mm.cfg` (GPL-3.0), read 2026-08-25. **No VORON has been connected to Studio.** |

The U1 remains the printer Studio prepares copies for, and the only one this
project has ever put on a wire.

## What "profile verified" actually got exercised

The VORON profile is not a table of specifications sitting unused. The same
functions the U1 uses were run against it — the Moonraker client's own parsing,
the capability resolver, Preflight, the Post-Slice Doctor, the send check, the
material plan — and they behaved as a printer that is not a U1 requires:

- one toolhead was read as one, not as four;
- a 250 mm cube was compared against instead of the U1's plate;
- object exclusion, which that configuration does not declare, was reported as a
  firmware feature this machine does not list, not as a broken printer;
- a four-tool job was blocked on a one-tool machine;
- a job that names this machine was accepted as sliced for it, where the old code
  would have told the user to re-slice it in Snapmaker Orca;
- and **what filament is loaded came back as unknown**, because nothing on that
  machine reports it. Studio did not invent one spool slot from one extruder.

That last one is the point. A tool count is not a spool count, and an abstraction
that quietly turns one into the other would look like it worked.

## What is not claimed

- **No VORON has been tested with Studio.** Not by this project, not on hardware,
  not once. Everything above about that machine is reasoning from a published
  configuration.
- **That configuration is a starting point, not a census.** It is a base file
  builders edit, and owners routinely add bed mesh, object exclusion, input
  shaping and pause/resume to it. Studio therefore treats a profile as saying only
  what is *expected*; a live object list from the machine is the only thing that
  settles a capability in either direction.
- **The 300 mm and 350 mm VORON 2.4 variants are not described** by this profile.
- **Studio still does not slice, and still prepares copies for the U1 only.**
  Nothing here changes what Studio produces.

## Adding your printer to this table

This table only grows from evidence, and evidence has to come from someone's
real machine — this project owns exactly one printer. If you run Studio
against a Moonraker printer that is not on this list yet:

```
u1convert verify-printer --host <your-printer-address> --port 7125
```

This is read-only: it only ever issues GET requests (probe, capabilities,
loaded-filament state), never a control call, and nothing about your printer
is changed. The address you give it is never copied into the output in the
first place — every check reports what the printer said, never the address
that was asked — and whatever else could identify your network goes through
the same redaction Studio's own support bundles use before you see it, so it
is safe to paste into a GitHub issue or discussion as-is.

Open an issue with the output attached, and say which printer it was. A
maintainer reading it is what turns "profile verified" into "hardware
verified" on this page — the tool that produced the evidence never assigns
that label to itself.

## Connecting a printer that is not a U1

Auto-detect looks for the hostnames the U1 publishes. Machines that publish none
are reached by typing the address, which is a supported way to connect rather than
a fallback — Studio does not scan the network, and address validation is the same
either way.

Studio then identifies the machine from what it reported. Moonraker publishes no
model name, so most printers stay unidentified, and that is a correct answer: every
check works on a machine Studio cannot name. Identification only ever adds
evidence to a sentence; it never decides whether a check runs.
