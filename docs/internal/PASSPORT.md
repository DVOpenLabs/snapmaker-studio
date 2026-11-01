# Job passport and connector contract

Evidence label: **fixture-tested**. Every claim below is exercised by `backend/tests/passport/`
with synthetic files and a synthetic command-line client. No real third-party program, printer,
slicer run or project file was used.

## What a passport is

A passport (`passport/1`) records which files a job was made from: the chain
original -> prepared -> sliced (a `generated` artifact works the same way), each file identified
by its bytes (`sha256` and size, `foundation.artifacts.ByteIdentity`), each link a
`foundation.artifacts.Derivation`. It also carries the virtual recipes and material mappings that
travelled with the job. It contains file **names**, never local paths.

Verification answers one question: are the files you have now the same bytes the passport
recorded? A changed file invalidates itself and everything derived from it. A file that cannot be
found or read leaves its lineage `unverified`, never `intact`.

### Who vouches for a link

Studio does not watch a prepare or a slice happen in this version. A chain you state when building
a passport is **declared** (by "user"). A passport read from a file is always **declared**: a
claim of `witness: local` in an imported file is downgraded and reported. If a declared parent
exists locally with different bytes the link is flagged `declared_mismatch`; it is never promoted
to a locally witnessed one. `intact` on a declared link means the bytes match what the declarer
wrote down, not that Studio saw the file being made.

### Recipes and material mappings

Retained when they decode; otherwise listed in `losses` with a reason. A recipe Studio cannot
interpret (unknown schema version, a missing component, a negative ratio) is reported lost or kept
with `execution_supported: false`. A mapping keeps only `slot_ref`, `material`, `colour` and
`spool`; any other field is listed as `field_not_retained:<name>`. Losses survive an export and
import round trip.

## Command line

```
u1convert passport export [--original F] [--prepared F] [--sliced F] [--recipes F] [--mappings F] [-o OUT]
u1convert passport import  PASSPORT [--base-dir DIR] [--path NAME=PATH ...]
u1convert passport verify  PASSPORT [--base-dir DIR] [--path NAME=PATH ...]
```

`export -o` refuses an existing file and refuses a path that is one of the inputs. No command
writes over or next to an input. `u1convert repair <file> --mode u1 -o <out>` writes a new file and
leaves the original unchanged (pinned by `test_7`).

### The contract an external program can rely on

1. stdout is exactly one top-level JSON object and nothing else, for every outcome Studio handles.
   Parse the whole of stdout. Studio does **not** promise that taking the text between the last
   `{` and the last `}` (`rfind("{")`) works: file names and other string values may contain
   braces, and the conformance test uses file names that do.
2. exit 0 means the command succeeded and the JSON says `"ok": true`. exit 1 means a handled
   failure or a negative answer (`verify` found a change, `import` could not use the document);
   the JSON is still present, with `"ok": false`. Failures Studio did not foresee are also one JSON
   object and exit 1, never a traceback.
3. A path argument that does not exist is rejected by the command-line layer before any of this:
   exit 2, usage text on stderr, **no JSON** on stdout. A caller must treat absent or invalid JSON
   as a failure, never as success. The exit code of `doctor` is a verdict signal (0 only for READY),
   so read the JSON.
4. `doctor <file> --json` prints one object that includes a `score` key (null when no score
   is given), `verdict`, the issue lists and `recommended_action`.

## HTTP routes (local service, `/passport/...`)

`/passport/build`, `/passport/import`, `/passport/verify`. They read and hash files; they make no
network request and never touch a printer. `build` returns a `paths` map (artifact id to the file it
read) for the caller's own later `verify` call; the passport never contains it.

## Limits of this first version

- Declared chains only; no integration with Prepare or a slicer run, so nothing is `local`.
- Files are hashed in place, not snapshotted: a file that changes between build and verify is
  detected, but a change during hashing is not.
- No real third-party client was exercised; the clients in the tests are synthetic.

### Path checks are not a sandbox

`u1convert/cli.py` registers the group (`cli.add_command(passport)`), so every command above runs
through the real `u1convert` entry point. Studio refuses, up front, a UNC or device path in any slash
style, a symlink or junction whose target is one of those, a folder given as the output, and an
existing output file. It never overwrites an input or an existing file.

Those checks are separate from the file operations that follow them. Validation reads the path; the
open, `mkstemp`, link or rename happens afterwards. Another process or principal that can modify the
output directory, or any ancestor of it, between the two steps can redirect that operation, for
example by swapping the directory for a link to a network share. Studio does not guard against that.
Use an output directory whose ancestors other users and programs cannot modify. The checks reduce
accidents; they are not a filesystem sandbox and not a guarantee that no network location is ever
reached. The known case is a race on `export -o` (CLI only; the HTTP routes never write a passport).
Input paths are read-only opens of regular files and are checked the same way, with the same
validation-versus-use gap; no separate input-path exploit has been demonstrated.
