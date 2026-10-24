// One side-effect-free sanitizer for acceptance evidence (result details, response summaries, error text), shared by
// checks.mjs (through geometry-expect.mjs) and job-journey.mjs so the two cannot drift apart. Importing this file runs nothing.
//
// Supported coverage (not universal path detection): Windows drive paths (either separator), UNC paths (including
// \\?\), file:// URLs, and POSIX paths that begin at /Users, /home, /media, /mnt, /Volumes, /root, /tmp or /var
// (so /var/tmp is covered). Each match runs to the next double quote or end of line, so spaces and apostrophes inside a
// folder name cannot end it early; text after a path on the same line is lost, which is the safe direction.
// NOT recognised: other POSIX roots (for example /opt, /srv, /private), forward-slash UNC (//server/share), ~/ paths,
// percent-encoded paths, and a drive path glued directly to a preceding letter (fooC:\x).
//
// A POSIX root counts only when it is not part of a longer path or URL: the character before the slash must not be a
// letter, digit, dot, tilde, percent, hyphen, underscore or another slash/backslash. So http://host/tmp/x and
// https://example.com/a/var/b are left intact, while "open /tmp/x" and "read '/var/tmp/x'" are redacted. A drive letter
// must not follow another letter, so http://127.0.0.1:7125/ is left alone. The one exception to both boundaries is a
// letter that is itself the end of a backslash escape (the n of \n, the t of \t, as JSON.stringify writes a newline or
// tab), so a path that starts a new line inside JSON-encoded text is still redacted.
const PATHISH = new RegExp(
  [
    String.raw`(?<!(?<!\\)[A-Za-z])[A-Za-z]:[\\/]+[^"\r\n]*`,
    String.raw`\\\\[^"\r\n]*`,
    String.raw`file:\/\/[^"\r\n]*`,
    String.raw`(?<!(?<!\\)[A-Za-z0-9_.~%\-])(?<![\\/])[\\/](?:Users|home|media|mnt|Volumes|root|tmp|var)[\\/][^"\r\n]*`,
  ].join("|"),
  "gi",
);

/** Replaces anything path-like in text with <path>. Pure: no I/O, no shared state (the regex is rebuilt per call). */
export function redact(text) {
  return String(text).replace(new RegExp(PATHISH.source, PATHISH.flags), "<path>");
}

/** The result line for one check: the detail is sanitized once, here, for both the console and the saved result. */
export function formatResult(name, ok, detail = "") {
  const clean = redact(detail);
  return { detail: clean, line: `${ok ? "PASS" : "FAIL"}  ${name}${clean ? `  — ${clean}` : ""}` };
}
