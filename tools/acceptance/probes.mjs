// Two throwaway HTTP servers the acceptance run owns, for the two provider
// questions that cannot be answered by pointing Studio at a real provider.
//
//  * The **counting probe** answers both providers' list routes with an empty
//    inventory and counts every request it receives. That turns "no provider is
//    configured" from an assertion into a measurement: configure it, see the
//    count rise; select None, see it not move.
//
//  * The **redirect probe** answers every request with `302` to a public host.
//    A local address is not a promise about where the *second* request goes, and
//    this is the only way to prove the installed build refuses to follow one —
//    the defect it is checking for was real, and it was in the shared transport
//    rather than in any one provider.
//
// Both listen on the loopback only, are started by the acceptance driver, and
// die with it. Usage:  node probes.mjs <countPort> <redirectPort>

import { createServer } from "node:http";
import { createCipheriv, createHash, pbkdf2Sync, randomBytes } from "node:crypto";
import { readFileSync } from "node:fs";

const [, , countPort, redirectPort, spooleasePort = "9403"] = process.argv;

const SPOOLEASE_KEY = process.env.SNAPSTUDIO_SPOOLEASE_KEY || "Fx7-tEsT";
const CSV = readFileSync(new URL("../../backend/tests/fixtures/providers/spoolease_3532f8d.csv", import.meta.url));
const CSV_SHA256 = "26c7ffdeec3d3a484a9361f642487cb87134ce61df14934366d2fa38b184ec4d";
const actualHash = createHash("sha256").update(CSV).digest("hex");
if (CSV.length !== 331 || !CSV.toString("utf8").endsWith("\n") || actualHash !== CSV_SHA256) {
  throw new Error(`SpoolEase fixture mismatch: ${CSV.length} bytes, sha256 ${actualHash}`);
}
const kdf = pbkdf2Sync(SPOOLEASE_KEY, "example_salt", 10000, 32, "sha256");
function encryptedPayload(payload, nonce = randomBytes(12)) {
  const cipher = createCipheriv("aes-256-gcm", kdf, nonce);
  const encrypted = Buffer.concat([cipher.update(payload, "utf8"), cipher.final(), cipher.getAuthTag()]);
  return nonce.toString("base64").slice(0, 16) + Buffer.concat([encrypted]).toString("base64").replace(/=+$/, "");
}
function encryptedCsv(mode) {
  const nonce = mode === "fixed_nonce" || mode === "empty_csv"
    ? Buffer.from("000102030405060708090a0b", "hex") : randomBytes(12);
  return encryptedPayload(mode === "empty_csv" ? "" : CSV.toString("utf8"), nonce);
}

let hits = 0;
const seen = [];

createServer((req, res) => {
  if (req.url === "/__hits") {
    // Read by the driver directly, never through Studio, so it cannot itself be
    // mistaken for provider traffic.
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ hits, seen }));
    return;
  }
  hits += 1;
  seen.push(req.url);
  res.writeHead(200, { "Content-Type": "application/json" });
  res.end("[]");
}).listen(Number(countPort), "127.0.0.1", () => {
  console.log(`counting probe on ${countPort}`);
});

createServer((req, res) => {
  res.writeHead(302, { Location: "http://example.com/api/v1/spool" });
  res.end();
}).listen(Number(redirectPort), "127.0.0.1", () => {
  console.log(`redirect probe on ${redirectPort}`);
});

createServer((req, res) => {
  if (req.url === "/__hits") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ provider: "spoolease" }));
    return;
  }
  res.writeHead(200, { "Content-Type": "text/plain" });
  const mode = new URL(req.url, "http://127.0.0.1").searchParams.get("mode");
  res.end(encryptedCsv(mode));
}).listen(Number(spooleasePort), "127.0.0.1", () => {
  console.log(`SpoolEase fake on ${spooleasePort}`);
});
