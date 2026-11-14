#!/usr/bin/env node
// Loopback-only synthetic Moonraker-style host for the "Prepare with a printer setup" journey.
// Dependency-free (node:http only). Binds 127.0.0.1 and nothing else. Read-only: only GET is served, any other
// method is a 405 and is counted. Every payload is hand-written and synthetic (no capture, no real device,
// no real address, name or serial).
//
// Four scenarios, one listener each, ports chosen by the OS unless given:
//   stock    four physical heads, four logical slots (a stock four-toolhead U1)
//   eight    four physical heads, eight logical slots (a hypothetical variant, not a capture)
//   invalid  three physical heads: complete, but not a U1, so the engine refuses it
//   failed   answers every read with a redirect, which the local service refuses to follow
//
// Usage:  node tools/dev/phase2-prepare-mock.mjs [--stock=PORT] [--eight=PORT] [--invalid=PORT] [--failed=PORT]
// It prints one JSON line {"stock":P,...,"pid":N} when ready and runs until stopped (Ctrl+C or SIGTERM).
import http from "node:http";

const arg = (name) => {
  const hit = process.argv.slice(2).find((a) => a.startsWith(`--${name}=`));
  const n = hit ? Number(hit.split("=")[1]) : 0;
  if (!Number.isInteger(n) || n < 0 || n > 65535) throw new Error(`--${name} must be a port from 0 to 65535`);
  return n;
};

/** A synthetic Moonraker bundle: `heads` physical heads, `slots` logical slots mapped round-robin onto them. */
export function bundleFor(heads, slots) {
  const colours = ["000000FF", "255B05FF", "4AB60AFF", "6F110FFF", "1B4F9CFF", "C9A227FF", "7A1FA2FF", "E0E0E0FF"];
  const per = (f) => Array.from({ length: slots }, (_, i) => f(i));
  return {
    server_info: { result: { klippy_connected: true, klippy_state: "ready", moonraker_version: "v0.9.3-synthetic", components: ["octoprint_compat"] } },
    objects_list: { result: { objects: ["webhooks", "toolhead", "print_task_config", ...Array.from({ length: heads }, (_, i) => (i === 0 ? "extruder" : `extruder${i}`))] } },
    print_task_config: { result: { status: { print_task_config: {
      filament_type: per(() => "PLA"), filament_sub_type: per(() => "Basic"),
      filament_color_rgba: per((i) => colours[i % colours.length]), filament_vendor: per(() => "Synthetic"),
      filament_exist: per(() => true), extruder_map_table: per((i) => i % heads),
    } } } },
    system_info: { result: { system_info: { product_info: { nozzle_diameter: Array.from({ length: heads }, () => 0.4), device_name: "SYNTHETIC-HOST", serial_number: "SYNTHETIC-0001" } } } },
  };
}

const SCENARIOS = {
  stock: { bundle: bundleFor(4, 4) },
  eight: { bundle: bundleFor(4, 8) },
  invalid: { bundle: bundleFor(3, 3) },
  failed: { redirect: true },
};

const requests = [];            // {scenario, method, path}: no headers, no query, no keys
function handler(scenario) {
  const spec = SCENARIOS[scenario];
  return (req, res) => {
    const path = (req.url ?? "").split("?")[0];
    requests.push({ scenario, method: req.method, path });
    const send = (code, body, headers = {}) => {
      const text = body === undefined ? "" : JSON.stringify(body);
      res.writeHead(code, { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(text), ...headers });
      res.end(text);
    };
    if (req.method !== "GET") return send(405, {});
    if (spec.redirect) return send(302, undefined, { Location: "http://127.0.0.1:9/" });
    const b = spec.bundle;
    switch (path) {
      case "/api/version": return send(200, { api: "0.1", server: "1.5.0", text: "OctoPrint (Moonraker 0.9.3)" });
      case "/server/info": return send(200, b.server_info);
      case "/printer/objects/list": return send(200, b.objects_list);
      case "/printer/objects/query": return send(200, b.print_task_config);
      case "/machine/system_info": return send(200, b.system_info);
      default: return send(404, { error: "not found" });
    }
  };
}

const servers = [];
const ports = {};
await Promise.all(Object.keys(SCENARIOS).map((name) => new Promise((resolve, reject) => {
  const server = http.createServer(handler(name));
  server.on("error", reject);
  server.listen(arg(name), "127.0.0.1", () => { ports[name] = server.address().port; servers.push(server); resolve(); });
})));
console.log(JSON.stringify({ ...ports, pid: process.pid }));

const stop = () => { for (const s of servers) s.close(); setTimeout(() => process.exit(0), 50); };
process.on("SIGINT", stop);
process.on("SIGTERM", stop);
// Written to stderr on exit so a run can show it never saw a write.
process.on("exit", () => {
  const writes = requests.filter((r) => r.method !== "GET").length;
  console.error(JSON.stringify({ served: requests.length, nonGet: writes }));
});
