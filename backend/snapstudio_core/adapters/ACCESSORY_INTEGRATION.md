# Explicit accessory setup integration

Setups and every normal Prepare setup selector can select multiACE, AFC, BMCU or
Sidecar explicitly. Stock host-only requests retain their previous shape.
multiACE contract 1 and AFC contract 1 offer a fixed-path GET against an explicitly
typed accessory host AND port, or imported JSON. BMCU accepts published command
text; Sidecar accepts marked G-code. Both also expose explicit JSON envelopes for
published transport/load-cell snapshots; unpublished state bodies stay unknown. Studio parses these strings, never executes
them. Unpublished status shapes remain unknown. No discovery scan occurs.

The contract version is chosen by the user through the named adapter option; it is
not a firmware-version detection claim. Accessory authentication is not implemented:
401/403 stays unavailable, and the OctoPrint key goes only to the separately chosen
physical printer host, never to an accessory origin. No retry or control request.

The main host fields optionally supply physical inventory through the existing
host reader. Complete host evidence can fill partial accessory inventory only when
all known heads/nozzles agree. A referenced missing head or contradictory nozzle
is refused. No head count comes from lane or filament count.

Parsers with no published logical-tool map return no logical slots. The user may
read once to inspect reported lane IDs, enter one lane per line in actual T0..Tn
order and read again. This is explicitly user-declared, not device-reported. Only
reported lane IDs are accepted. No slot enumeration or head binding is guessed.
Preparing an incomplete inventory remains paused. Imported observations stay
historical; reading a host does not freshen old accessory material or lane facts.
This does not establish feeder scheduling, load commands, material compatibility,
or real-device success. The existing conversion engine remains the authority.

Inputs and late replies are invalidated on edits. An edited Prepare setup stays
paused until re-read or explicitly cleared; editing never silently selects stock. Keys are held only in memory.
Request body/snapshot cap is 256 KiB, declared map cap 64. Each explicit accessory
or optional physical-host request has a 0.55-second timeout (six reads maximum);
legacy host-only timeout is unchanged. Slow/unavailable services can be refused.

Evidence: published-shape synthetic fixtures, real local conversion and owned
loopback GET service. No real multiACE/AFC/BMCU/Sidecar or printer was contacted.

Device-reported logical slots or bindings are authoritative: an additional user slot_map is refused, never silently substituted. Physical-head reasons retain their host/device attribution. Live transport refusals are unavailable reads with fixed netguard reasons, not claims that a local address is outside the LAN.
