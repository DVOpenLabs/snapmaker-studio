# External command-line contract

Other programs may call the `u1convert` command to check a model and to write a
prepared copy. This is the contract they can rely on. It is pinned by
`backend/tests/test_external_cli_contract.py`, which runs the real entry point in a
subprocess. There is no separate API or background service for this.

| Call | Output | Exit code |
|---|---|---|
| `u1convert doctor <file> --json` | one JSON object on stdout | `0` only when the verdict is `READY`; otherwise `1` |
| `u1convert repair <file> --mode u1 -o <out>` | a new file at `<out>` | the caller should check that `<out>` exists |

- **The exit code of `doctor` is a verdict signal, not a transport failure.** A valid
  `CONVERTIBLE` answer exits `1` with complete JSON. Read the JSON; do not require exit `0`.
- JSON fields a caller reads: `verdict`, `score`, `validation_issues`,
  `compatibility_issues`, `recommended_action`, `family`, `is_u1`.
- `repair` never modifies its input; it writes a new file. It may also write a
  `FIX_REPORT.json` next to the output.
- Everything is local: nothing is uploaded.

## What is and is not verified

- Verified: the source command-line entry point, run with a Python interpreter, against
  authored test files.
- **Not verified: a packaged or installed executable.** Run the same checks against one with
  `SNAPSTUDIO_CLI_EXE=<path to u1convert> pytest backend/tests/test_external_cli_contract.py`
  and record the result before claiming packaging works.
