# Do I have enough filament to finish this print?

> **State:** Spoolman, Bambuddy and the "Your spool notes" screen below all ship
> in the v1.2.0 desktop app.

A printer knows which spool is in which slot, because it is looking at it. It
knows nothing at all about how much filament is left on that spool. So the
question people actually ask before pressing print is one no printer can answer,
and Studio said "unknown" to it on every setup.

Something on your network may know. **Spoolman** tracks spools and what has been
used from them; **Bambuddy** keeps a spool inventory alongside its printer
management. Studio can read either — read-only, over your own network, optional.

## Setting it up

**Settings → Materials provider.**

1. Choose **Spoolman** or **Bambuddy**.
2. Type the address of the machine it runs on: `spoolman.local:7912` or
   `bambuddy.local:8000`, or the IP.
3. Press **Test connection**.
4. Say which numbering your slots use — 1 to 4, or 0 to 3 — and then which spool
   is in which slot.

That is all of it. No account, no cloud, and Studio does not scan your network
looking for anything.

Changing provider clears the address and the slot mapping, because a spool id
only means something to the provider that issued it. Carried across, a mapping
would point at whatever spool happened to share the number — and Studio would
then report that spool's material for the slot, confidently and with no reason
to be right.

### If Bambuddy asks Studio to sign in

Bambuddy can be run with authentication switched on, and then it wants an API key
on every request. Studio has nowhere safe to keep one, so it says so rather than
storing a key in the clear. A Bambuddy that does not require a key reads normally.

### Why it asks about slot numbering

A person counts the slots on a printer 1, 2, 3, 4. G-code counts them 0, 1, 2, 3.
Guess wrong and every spool is one slot out, and Studio then reports the wrong
material for every slot with complete confidence — which is worse than not
knowing. So it asks instead of guessing.

### What "Test connection" tells you

Two numbers, because they are genuinely different:

- how many spools the provider has;
- how many of those carry a weight **something is actually keeping track of**.

Both providers report what a spool started with until something prints from it. A
shelf of spools you have just registered will all report a full kilogram, and that
is a declared size rather than a measurement. Studio treats those as estimates,
and says so, rather than letting a number that has never been updated stop you
printing.

Bambuddy has no remaining-weight field at all: it stores what the label claimed
and what has been used, and Studio subtracts one from the other. That figure is
arithmetic, and Studio never presents it as something Bambuddy is keeping — unless
the spool has been weighed, which writes both the figure and the moment it was
true.

## What Studio will and will not say

| What it knows | What it says |
|---|---|
| A tracked weight, updated recently, and the job needs more | **Not enough** — this blocks the send |
| A tracked weight, updated recently, and enough for the job | Enough, with the figure and its age |
| A tracked weight nobody has updated in over a week | A warning, with how old it is. Never a refusal |
| A weight worked out from the spool's declared size | A warning. It is arithmetic, not a record |
| A weight with no date at all | A warning. Nothing says it is still true |
| Nothing tracking the spool | **Unknown** — go and look at it |
| The provider is unreachable | **Unknown**. Not "enough", and not "empty" |

A blocker is the strongest thing Studio says, so it has to be earned: only a
figure something is genuinely keeping, recent enough to still be true, can stop a
send. Everything else warns. The reason is not caution for its own sake — a
person refused a print over bookkeeping learns to ignore the refusals, and the
next one might be right.

Past a week, a figure warns and can never be the sole reason a send is refused.

## The printer and the provider disagreeing

The printer is authoritative about **what is physically in the slot**, because it
can see it. A provider adds what the machine cannot know: which spool this is, and
how much is on it.

When they disagree, Studio shows the disagreement and keeps the printer's answer:

> Printer reports PLA; your provider mapping says PETG. Check slot 2.

It does not pick a winner quietly, and it does not throw away the provider's
remaining weight because the material disagreed — those are two separate claims
about the same slot, and the second may still be right.

## On a printer that reports no filament at all

Most Klipper printers publish nothing about what is loaded; the Snapmaker U1 is
unusual in doing so. On a machine that does not, your mapping is the only source —
and Studio says so in those words:

> PLA is mapped to this slot and matches what the job expects. This printer does
> not report its own filament, so that is your mapping rather than something the
> machine has confirmed.

A provider mapping is never presented as an observation. Studio will still use
the remaining weight, because a spool you told it about having 43 g on it is a
real reason to expect an 87 g job to run out.

## What Studio never does

- **Writes to a provider.** Studio does not create spools in Spoolman or
  Bambuddy, does not decrement their remaining weight, and does not mark a spool
  used after a print. Consumption tracking belongs to the tool that owns the data;
  two tools writing the same number is how they end up disagreeing.
- **Requires a provider.** A stock printer with no other software is a first-class
  setup. Without a provider, Studio says it does not know, which is true.
- **Leaves your network.** The address is checked to be on your own network —
  loopback, a private range, a tailnet, or a `.local` style name — before any
  request is opened. A public address is refused rather than fetched, and so is a
  local address that answers with a redirect to a public one.
- **Invents a figure.** A provider that cannot say how much is left produces
  unknown, everywhere, all the way to the send button.

## Your spool notes

![Your spool notes, with two notes recorded](screenshots/v1.2.0/spool-notes.png)
![Your spool notes, before any note is added](screenshots/v1.2.0/spool-notes-empty.png)

Since v1.1.0 the engine has kept your own notes on a spool — material,
colour, vendor, starting and remaining weight — stored in Studio's local library
on your machine, one note per printer slot. They pass through the same rules as
a provider:

- A figure you typed is labelled as yours. A figure Studio worked out by
  subtracting a job's usage from it is labelled differently, and the two never
  look the same.
- The printer stays authoritative about what is physically in the slot. A slot
  the printer reports empty can never be overridden by a note.
- Studio subtracts from a note's remaining weight only when explicitly asked to
  record a job's usage — never while reading, planning or sending a job.

In the desktop app: Settings → **Materials provider** card →
**Your spool notes**.
Each slot shows its note, or "Add a note". A weight you type reads "entered by
you"; after **Record filament used** — which asks you to confirm the grams first —
it reads "estimated from what you recorded". Changing the material, subtype,
colour or vendor to a different spool resets the weight to "no weight recorded";
clearing a field does not. Switching between None, Spoolman and Bambuddy never
touches your notes. If two notes exist for one slot (the same printer saved
under two spellings of its address), neither is used and the slot shows
a message such as "Two notes exist for slot 1 — remove one" until you remove one.

## Other providers

Material providers normalise into a shared read-only contract; **Spoolman and
Bambuddy are currently implemented**. Two is not "any provider works" — it is two
providers whose wire formats have almost nothing in common, proved to produce the
same decisions from the same facts. `material_providers.py` is the only place a
provider's name is turned into anything; past it the name is a label on a fact.

**U1Hub** was re-examined on 2026-08-25 and is deliberately **not** integrated. It
does expose `/api/spools` and `/api/slots`, but they carry no version or schema,
are undocumented for use by other tools, sit behind its own password gate, and are
written for its own interface — and, decisively, U1Hub tracks spool *identity*
(brand, material, colour) and not remaining weight, so it has nothing to answer
this question with. Studio has never read its internal files and will not.
See [interop/U1HUB_INTEROP_PROPOSAL.md](interop/U1HUB_INTEROP_PROPOSAL.md).
