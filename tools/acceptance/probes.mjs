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
import { createCipheriv, pbkdf2Sync, randomBytes } from "node:crypto";

const [, , countPort, redirectPort, spooleasePort = "9403"] = process.argv;

const SPOOLEASE_KEY = process.env.SNAPSTUDIO_SPOOLEASE_KEY || "Fx7-tEsT";
const CSV = `1,04A1B2C3D4E5F6,PLA,Basic,Galaxy Black,000000,,Fixture Filaments,1000,250,1250,812,Generic PLA,1750000000,1750000000,y,,AABIQQ,n,tag,ntag215
2,04B1B2C3D4E5F7,PETG,HF,"Signal Blue, matte",0055FF,"Second shelf, ""left""",Fixture Filaments,1000,,1240,640,Generic PETG,1750086400,,y,,,n,manual,
3,,ABS,,Red,FF0000,,,1000,,,,,,,,,,n,,`;
const kdf = pbkdf2Sync(SPOOLEASE_KEY, "example_salt", 10000, 32, "sha256");
function encryptedPayload(payload, nonce = randomBytes(12)) {
  const cipher = createCipheriv("aes-256-gcm", kdf, nonce);
  const encrypted = Buffer.concat([cipher.update(payload, "utf8"), cipher.final(), cipher.getAuthTag()]);
  return nonce.toString("base64").slice(0, 16) + Buffer.concat([encrypted]).toString("base64").replace(/=+$/, "");
}
function encryptedCsv(mode) {
  const nonce = mode === "fixed_nonce" || mode === "empty_csv"
    ? Buffer.from("000102030405060708090a0b", "hex") : randomBytes(12);
  return encryptedPayload(mode === "empty_csv" ? "" : CSV, nonce);
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
