// Synthetic path builders for the sanitizer tests. Every identity used with them is fictional ("Avery", "Fictional
// Workshop", "Sample Models"): none is a real person, machine or folder. The paths are assembled from readable segments
// at run time only so that no absolute-path literal is tracked in the repository; this hides nothing, and the segments
// stay plainly visible at each call site. Importing this file runs nothing.

/** A Windows path: win("C:", "Fictional Workshop", "x.3mf") -> C:\Fictional Workshop\x.3mf (use sep "/" for the other style). */
export const win = (drive, ...parts) => [drive, ...parts].join("\\");
export const winSlash = (drive, ...parts) => [drive, ...parts].join("/");

/** A UNC path: unc("fileserver", "share", "x.3mf") -> \\fileserver\share\x.3mf */
export const unc = (host, ...parts) => `\\\\${[host, ...parts].join("\\")}`;

/** A POSIX path: posix("tmp", "sample", "x.3mf") -> /tmp/sample/x.3mf */
export const posix = (...parts) => `/${parts.join("/")}`;

/** A file URL: fileUrl("tmp", "sample", "x.3mf") -> file:///tmp/sample/x.3mf */
export const fileUrl = (...parts) => `file://${posix(...parts)}`;
