# Convergence policy — replaces the change freeze

**The freeze this file used to describe is cancelled.** It was the wrong call.

It read the Innovation Fund period as something to survive: hold beta.24 still,
spend the remaining weeks on documentation and presentation, and hope the
committee reads carefully. The other 40 projects were shipping the whole time. A
project that stops developing while its field develops does not look careful; it
looks finished in the wrong sense.

The correct reading: being among the Phase 1 projects is an opportunity to
make Studio genuinely complete — and then to stop calling it a beta.

## What replaces it

**Controlled convergence toward stable.** Development continues. It is aimed at
one thing: a product whose workflow is finished end to end, released as a stable
version rather than the twenty-fifth beta.

A runtime change ships when it satisfies at least one of these:

1. it materially improves the complete Studio workflow;
2. it closes a usability gap another project has already shown matters;
3. it increases Studio's own advantage — being right about a file and a printer;
4. it removes a novice dead end;
5. it strengthens real-printer integration;
6. it improves interoperability with the rest of the ecosystem;
7. it removes beta-quality behaviour;
8. it increases reliability or correctness.

No feature count. No arbitrary freeze. "Interesting" is still not a reason.

## What that produced

`v0.4.0` — the first stable release, and the closed loop:

| Was | Now |
|---|---|
| Studio checked the *project* and stopped at the slicer | It reads the **sliced G-code** and reports what the printer will actually execute |
| Printer comparison happened before slicing only | The sliced job is joined to the **live printer**: tools against loaded slots, materials against what is loaded, bed against the real bed |
| Cost estimated from whatever the project carried | Costed from the **grams and time the slicer measured** — and refuses to split purge out of a total the slicer did not split |
| Bug reports needed a user to gather facts by hand | A **support bundle** that redacts identity before it is written, and shows the user the contents first |
| `.stl` and `.3mf` on the command line | `.gcode` too, so a sliced job opens straight into the Post-Slice Doctor |

## What is still true

The rules that made Studio worth trusting did not move:

- **Studio does not slice.** Snapmaker Orca does. Reading a G-code file is not
  producing one.
- **Originals are never modified.**
- **Unknown stays unknown.** Every new check can return "Studio can't tell", and
  several usually do.
- **No autonomous printer control.** Nothing added here sends, starts, heats or
  moves anything.
- **Nothing leaves the machine.** The support bundle writes a file; sending it is
  the user's decision, made elsewhere.

## After stable

Patch releases for defects. Features go through the same eight tests above. The
deferred list — painted-colour enumeration, a second printer, OBJ/GLB input,
macOS and Linux builds — is in [NEXT_MOVES.md](NEXT_MOVES.md), and none of it is
required for the workflow to be complete.
