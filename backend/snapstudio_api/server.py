"""Loopback JSON server for the desktop app.

Binds 127.0.0.1 only. GET /health is open (for liveness probing); POST /doctor
requires the per-launch X-Auth-Token. On start, prints one JSON line
{"port": N, "token": "..."} to stdout so the Tauri shell can connect.
"""
from __future__ import annotations
import hmac
import json
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from . import _lifeline
from . import service
from . import request_validation as rv
from .request_validation import ValidationError

# Request bodies here are small JSON objects (paths, numbers, short option maps).
# 1 MiB is orders of magnitude more than any real call needs and bounds what an
# unauthenticated local caller can make the server allocate.
MAX_REQUEST_BYTES = 1024 * 1024


def _watch_parent_then_exit() -> None:
    """When launched by the desktop shell, exit as soon as the parent process
    dies — for ANY reason (window close, crash, or force-kill). This guarantees
    no orphan sidecar survives the app. No-op if not launched with a parent PID
    or on non-Windows platforms.
    """
    ppid = os.environ.get("SNAPSTUDIO_PARENT_PID")
    if not ppid:
        return
    try:
        import ctypes
        from ctypes import wintypes

        if not hasattr(ctypes, "windll"):  # non-Windows
            return
        pid = int(ppid)

        PROCESS_SYNCHRONIZE = 0x00100000
        INFINITE = 0xFFFFFFFF

        k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        # Declare explicit signatures — without these, ctypes defaults the
        # HANDLE return to a 32-bit int and truncates it on 64-bit Windows,
        # silently breaking the wait. wintypes.HANDLE is a full-width pointer.
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.WaitForSingleObject.restype = wintypes.DWORD
        k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]

        handle = k32.OpenProcess(PROCESS_SYNCHRONIZE, False, pid)
        if not handle:
            return

        def _wait():
            k32.WaitForSingleObject(handle, INFINITE)
            os._exit(0)

        threading.Thread(target=_wait, daemon=True).start()
    except (AttributeError, OSError, ValueError):
        # Non-Windows (no windll) or bad PID — skip; not fatal.
        return


def cors_allow_origin(origin: str | None) -> str | None:
    """Return the Origin to echo in Access-Control-Allow-Origin, or None to omit it.

    Loopback-only service: allow only local app/dev origins (the Tauri webview and
    Vite dev server) instead of a wildcard, so an arbitrary remote web page can no
    longer read even unauthenticated responses. POSTs remain token-gated regardless.
    Covers Windows/Linux/macOS Tauri webview origins and localhost dev ports.
    """
    if not origin:
        return None
    o = origin.strip()
    if o == "tauri://localhost":
        return o
    try:
        host = (urlparse(o).hostname or "").lower()
    except ValueError:
        return None
    if host in ("localhost", "127.0.0.1", "tauri.localhost", "::1") or host.endswith(".localhost"):
        return o
    return None


def _make_handler(token: str):
    class Handler(BaseHTTPRequestHandler):
        # HTTP/1.1, so a client can keep one connection and reuse it. The default
        # is HTTP/1.0, which closes after every response — and the app makes a
        # dozen calls to draw a single page, each one taking a fresh source port
        # and leaving it in TIME_WAIT. On a machine that is short of ports (one
        # here had 14,000 connections held open by Docker Desktop) that is the
        # difference between Studio working and Studio not answering at all.
        # Every response this handler writes carries an accurate Content-Length,
        # which is what makes persistent connections safe.
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):  # silence default logging
            pass

        def _cors(self):
            # Loopback-only service; the Tauri webview is a different origin, so
            # responses need CORS headers or the in-app fetch is blocked. Echo only
            # allowed local origins (not '*'); requests with no Origin (non-browser)
            # need no header.
            allowed = cors_allow_origin(self.headers.get("Origin"))
            if allowed:
                self.send_header("Access-Control-Allow-Origin", allowed)
                self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Auth-Token")

        def _send(self, code: int, obj: dict):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self._cors()
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            # Preflight for POST requests carrying the X-Auth-Token header.
            self.send_response(204)
            self._cors()
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self):
            if self.path == "/health":
                self._send(200, service.health())
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            # Always drain the request body BEFORE responding. Replying (e.g. 401)
            # with an unread body resets the connection on Windows (WinError 10053).
            # Guard the parse (a non-numeric Content-Length must not crash the
            # handler), but still drain any valid body before responding — an
            # unread body resets the connection on Windows (WinError 10053).
            try:
                length = int(self.headers.get("Content-Length", 0) or 0)
            except (TypeError, ValueError):
                self._send(400, {"error": "invalid Content-Length"})
                return
            if length < 0 or length > MAX_REQUEST_BYTES:
                # Refuse before allocating. Every real request here is a small JSON
                # object of paths and numbers; a multi-megabyte body is either a bug
                # or an attempt to exhaust memory ahead of the token check.
                self._send(413, {"error": "request too large"})
                return
            raw = self.rfile.read(length) if length > 0 else b""
            if not hmac.compare_digest(self.headers.get("X-Auth-Token") or "", token):
                self._send(401, {"error": "unauthorized"})
                return
            try:
                data = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                self._send(400, {"error": "invalid JSON"})
                return
            if self.path == "/doctor":
                path = data.get("path")
                if not path:
                    self._send(400, {"error": "missing 'path'"})
                    return
                try:
                    result = service.doctor(path)
                    service.record_diagnosis(path, result)  # best-effort index
                    self._send(200, result)
                except Exception:  # adapter must not crash the server
                    self._send(500, {"error": "internal error"})
            elif self.path == "/first_layer_check":
                try:
                    self._send(200, service.first_layer_check(data.get("symptom", "")))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/quality_check":
                try:
                    self._send(200, service.quality_check(data.get("symptom", ""), data.get("path")))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/fix_history":
                try:
                    self._send(200, service.fix_history(
                        source=rv.optional_str(data, "source", "") or None,
                        limit=rv.optional_int(data, "limit", 50)))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/fix_original":
                try:
                    self._send(200, service.fix_original(
                        rv.require_path_string(data, "output")))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/fix_history_export":
                try:
                    self._send(200, service.fix_history_export(
                        limit=rv.optional_int(data, "limit", 50)))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/color_plan":
                try:
                    self._send(200, service.color_plan(
                        rv.require_path_string(data),
                        toolheads=(rv.optional_int(data, "toolheads", 0) or None)))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/fidelity":
                try:
                    self._send(200, service.fidelity_audit(
                        rv.require_path_string(data, "original"),
                        rv.require_path_string(data, "prepared")))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/preflight":
                try:
                    self._send(200, service.preflight(
                        rv.require_path_string(data),
                        host=rv.optional_str(data, "host", "") or None,
                        port=rv.require_port(data)))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/watch_folder":
                try:
                    self._send(200, service.watch_folder(
                        rv.require_path_string(data, "folder"),
                        project_path=rv.optional_str(data, "project_path", "") or None))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/slice_provenance":
                try:
                    self._send(200, service.slice_provenance(
                        rv.require_path_string(data, "project_path"),
                        rv.require_path_string(data, "gcode_path")))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/print_plan":
                try:
                    self._send(200, service.print_plan(rv.require_path_string(data)))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/provider/test":
                # Read-only, and the address is validated inside the engine before
                # anything is opened. A provider that is not there is an answer,
                # not a 500.
                try:
                    self._send(200, service.provider_test(
                        rv.optional_str(data, "url", ""),
                        provider=rv.optional_str(data, "provider", "") or None))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/material_plan":
                try:
                    slot_map = data.get("slot_map")
                    self._send(200, service.material_plan(
                        rv.require_path_string(data),
                        host=rv.optional_str(data, "host", "") or None,
                        port=rv.require_port(data),
                        spoolman=rv.optional_str(data, "spoolman", "") or None,
                        provider=rv.optional_str(data, "provider", "") or None,
                        provider_url=rv.optional_str(data, "provider_url", "") or None,
                        slot_map=slot_map if isinstance(slot_map, dict) else None,
                        slot_base=rv.optional_int(data, "slot_base", 0)))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/send_check":
                try:
                    slot_map = data.get("slot_map")
                    self._send(200, service.send_check(
                        rv.require_path_string(data),
                        host=rv.optional_str(data, "host", "") or None,
                        port=rv.require_port(data),
                        include_timeline=bool(data.get("include_timeline")),
                        project_path=rv.optional_str(data, "project_path", "") or None,
                        spoolman=rv.optional_str(data, "spoolman", "") or None,
                        provider=rv.optional_str(data, "provider", "") or None,
                        provider_url=rv.optional_str(data, "provider_url", "") or None,
                        slot_map=slot_map if isinstance(slot_map, dict) else None,
                        slot_base=rv.optional_int(data, "slot_base", 0)))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/diagnostics_preview":
                try:
                    from snapstudio_core import diagnostics as diag
                    self._send(200, diag.preview(
                        project_path=rv.optional_str(data, "project_path", "") or None,
                        gcode_path=rv.optional_str(data, "gcode_path", "") or None,
                        host=rv.optional_str(data, "host", "") or None,
                        port=rv.require_port(data)))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/diagnostics_build":
                try:
                    from snapstudio_core import diagnostics as diag
                    self._send(200, diag.build(
                        out_dir=rv.optional_str(data, "out_dir", "") or None,
                        project_path=rv.optional_str(data, "project_path", "") or None,
                        gcode_path=rv.optional_str(data, "gcode_path", "") or None,
                        host=rv.optional_str(data, "host", "") or None,
                        port=rv.require_port(data)))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/gcode_facts":
                try:
                    self._send(200, service.gcode_facts(rv.require_path_string(data)))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/post_slice":
                try:
                    self._send(200, service.post_slice(
                        rv.require_path_string(data),
                        host=rv.optional_str(data, "host", "") or None,
                        port=rv.require_port(data),
                        project_path=rv.optional_str(data, "project_path", "") or None))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/sliced_cost":
                try:
                    self._send(200, service.sliced_cost(
                        rv.require_path_string(data),
                        price_per_kg=rv.optional_float(data, "price_per_kg", 20.0),
                        currency=rv.optional_str(data, "currency", "$") or "$"))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/placement_check":
                try:
                    self._send(200, service.placement_check(rv.require_path_string(data)))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/prepare_placed":
                try:
                    self._send(200, service.prepare_placed(
                        rv.require_path_string(data),
                        out_dir=data.get("out_dir") or None))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/project_cost":
                try:
                    prices = data.get("prices")
                    self._send(200, service.project_cost(
                        rv.require_path_string(data),
                        price_per_kg=rv.optional_positive_float(data, "price_per_kg", 20.0),
                        currency=rv.optional_str(data, "currency", "$") or "$",
                        prices=prices if isinstance(prices, dict) else None))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/ecosystem_advice":
                try:
                    installed = data.get("installed")
                    self._send(200, service.ecosystem_advice(
                        rv.require_path_string(data),
                        installed=installed if isinstance(installed, dict) else None))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/project_traits":
                try:
                    self._send(200, service.project_traits(rv.require_path_string(data)))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/source_compatibility":
                path = data.get("path")
                if not path:
                    self._send(400, {"error": "missing 'path'"})
                    return
                try:
                    self._send(200, service.source_compatibility(path))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/scale_preview":
                try:
                    path = rv.require_path_string(data)
                    scale = rv.require_finite_float(data, "scale_percent")
                    self._send(200, service.scale_preview(path, scale))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/scale_options":
                try:
                    path = rv.require_path_string(data)
                    printer = rv.optional_str(data, "printer", "snapmaker_u1")
                    margin = rv.optional_float(data, "margin_mm", 5.0)
                    self._send(200, service.scale_options(path, printer, margin))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/print_failure_troubleshoot":
                try:
                    path = rv.require_path_string(data)
                    kg = data.get("known_good_print")
                    if isinstance(kg, str):
                        kg = kg.strip().lower() in ("true", "1", "yes")
                    elif kg is not None:
                        kg = bool(kg)
                    self._send(200, service.print_failure_troubleshoot(
                        path,
                        rv.optional_str(data, "symptom", "fails_even_with_supports"),
                        kg,
                        rv.optional_str(data, "known_good_material", "") or None,
                        rv.optional_str(data, "failed_material", "") or None,
                        rv.optional_str(data, "failure_stage", "unknown")))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/model_search":
                try:
                    self._send(200, service.model_search_query(
                        data.get("query", ""), data.get("filters") or {}))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/compatibility_check":
                path = data.get("path")
                if not path:
                    self._send(400, {"error": "missing 'path'"})
                    return
                try:
                    self._send(200, service.compatibility_check(path))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/convert":
                path = data.get("path")
                if not path:
                    self._send(400, {"error": "missing 'path'"})
                    return
                prepare_mode = data.get("prepare_mode", "preserve")
                if prepare_mode == "u1":
                    prepare_mode = "recommended"
                if prepare_mode not in ("preserve", "recommended"):
                    self._send(400, {"error": "prepare_mode must be 'preserve' or 'recommended'"})
                    return
                dry_run = data.get("dry_run", False)
                if not isinstance(dry_run, bool):
                    self._send(400, {"error": "dry_run must be a boolean"})
                    return
                try:
                    result = service.convert(path, data.get("out_dir"), prepare_mode, dry_run)
                    if not dry_run:
                        service.record_conversion(path, result)  # best-effort index
                    self._send(200, result)
                except ValueError as e:
                    self._send(400, {"error": str(e)})
                except Exception:  # adapter must not crash the server
                    self._send(500, {"error": "internal error"})
            elif self.path == "/prepare_scaled":
                path = data.get("path")
                scale = data.get("scale_percent")
                if not path or scale is None:
                    self._send(400, {"error": "missing 'path' or 'scale_percent'"})
                    return
                try:
                    result = service.prepare_scaled(path, float(scale), data.get("out_dir"))
                    if not result.get("blocked"):
                        service.record_conversion(path, result)  # best-effort index
                    self._send(200, result)
                except ValueError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/diff":
                a, b = data.get("a"), data.get("b")
                if not a or not b:
                    self._send(400, {"error": "missing 'a' or 'b'"})
                    return
                try:
                    self._send(200, service.diff(a, b))
                except Exception:  # adapter must not crash the server
                    self._send(500, {"error": "internal error"})
            elif self.path == "/insights":
                path = data.get("path")
                if not path:
                    self._send(400, {"error": "missing 'path'"})
                    return
                try:
                    self._send(200, service.insights(path))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/report":
                path = data.get("path")
                if not path:
                    self._send(400, {"error": "missing 'path'"})
                    return
                try:
                    self._send(200, service.report(path))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/canonical":
                path = data.get("path")
                if not path:
                    self._send(400, {"error": "missing 'path'"})
                    return
                try:
                    self._send(200, service.canonical(path))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/mesh":
                path = data.get("path")
                if not path:
                    self._send(400, {"error": "missing 'path'"})
                    return
                try:
                    self._send(200, service.mesh(path))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/strategies":
                try:
                    self._send(200, service.strategies())
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/strategy/recommend":
                path = data.get("path")
                if not path:
                    self._send(400, {"error": "missing 'path'"})
                    return
                try:
                    self._send(200, service.strategy_recommend(path))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/printer/discover":
                try:
                    self._send(200, service.printer_discover(data.get("hosts")))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/printer/status":
                host = data.get("host")
                if not host:
                    self._send(400, {"error": "missing 'host'"})
                    return
                try:
                    self._send(200, service.printer_status(host, rv.require_port(data)))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/printer/history":
                host = data.get("host")
                if not host:
                    self._send(400, {"error": "missing 'host'"})
                    return
                try:
                    self._send(200, service.printer_history(host, rv.require_port(data), rv.optional_int(data, "limit", 20)))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/printer/file_metadata":
                host = data.get("host"); fn = data.get("filename")
                if not host or not fn:
                    self._send(400, {"error": "missing 'host' or 'filename'"})
                    return
                try:
                    self._send(200, service.printer_file_metadata(host, fn, rv.require_port(data)))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/printer/diagnostics":
                host = data.get("host")
                if not host:
                    self._send(400, {"error": "missing 'host'"})
                    return
                try:
                    self._send(200, service.printer_diagnostics(host, rv.require_port(data)))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/printer/bed_mesh":
                host = data.get("host")
                if not host:
                    self._send(400, {"error": "missing 'host'"})
                    return
                try:
                    self._send(200, service.printer_bed_mesh(host, rv.require_port(data)))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path in ("/printer/control/pause", "/printer/control/resume",
                               "/printer/control/cancel", "/printer/control/start",
                               "/printer/control/emergency_stop", "/printer/job_queue",
                               "/printer/upload_gcode"):
                # Printer Hub Phase B control. The Studio UI is the safety gate: it
                # confirms start/cancel/emergency-stop before calling these. The backend
                # only relays the user-confirmed action to Moonraker.
                host = data.get("host")
                if not host:
                    self._send(400, {"error": "missing 'host'"})
                    return
                port = rv.require_port(data)
                try:
                    if self.path == "/printer/control/pause":
                        out = service.printer_pause(host, port)
                    elif self.path == "/printer/control/resume":
                        out = service.printer_resume(host, port)
                    elif self.path == "/printer/control/cancel":
                        out = service.printer_cancel(host, port)
                    elif self.path == "/printer/control/start":
                        out = service.printer_start(host, data.get("filename"), port)
                    elif self.path == "/printer/control/emergency_stop":
                        out = service.printer_emergency_stop(host, port)
                    elif self.path == "/printer/job_queue":
                        out = service.printer_job_queue(host, port)
                    else:  # /printer/upload_gcode
                        expect = data.get("expect_state")
                        slot_map = data.get("slot_map")
                        out = service.printer_upload_gcode(
                            host, data.get("path"), port,
                            # What the user was shown when they decided to send. The
                            # upload re-reads the same things and refuses if they
                            # have moved on.
                            expect_state=expect if isinstance(expect, dict) else None,
                            project_path=rv.optional_str(data, "project_path", "") or None,
                            spoolman=rv.optional_str(data, "spoolman", "") or None,
                            provider=rv.optional_str(data, "provider", "") or None,
                            provider_url=rv.optional_str(data, "provider_url", "") or None,
                            slot_map=slot_map if isinstance(slot_map, dict) else None,
                            slot_base=rv.optional_int(data, "slot_base", 0))
                    self._send(200, out)
                except (ValidationError, ValueError) as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(502, {"error": "could not reach the printer or it refused the command"})
            elif self.path == "/first_layer":
                path = data.get("path")
                if not path:
                    self._send(400, {"error": "missing 'path'"})
                    return
                try:
                    self._send(200, service.first_layer(path, data.get("host"), rv.require_port(data)))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/toolhead_fit":
                path = data.get("path")
                if not path:
                    self._send(400, {"error": "missing 'path'"})
                    return
                try:
                    self._send(200, service.toolhead_fit(path, data.get("host"), rv.require_port(data)))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/cost_estimate":
                try:
                    path = rv.require_path_string(data)
                    price = rv.optional_positive_float(data, "price_per_kg", 20.0)
                    currency = rv.optional_str(data, "currency", "$")
                    self._send(200, service.cost_estimate(path, price, currency))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/batch_pricing":
                paths = data.get("paths")
                if not paths or not isinstance(paths, list):
                    self._send(400, {"error": "missing 'paths' (non-empty list)"})
                    return
                try:
                    factor_keys = ("price_per_kg", "power_w", "electricity_per_kwh",
                                   "machine_price", "machine_life_hours", "labor_hours",
                                   "labor_rate", "failure_rate_pct", "markup_pct",
                                   "marketplace_fee_pct", "grams_override", "print_hours",
                                   "packaging", "shipping_cost", "shipping_charged",
                                   "material_density")
                    factors = {k: rv.optional_float(data, k, 0.0) for k in factor_keys if data.get(k) is not None}
                    self._send(200, service.batch_pricing(
                        paths, str(data.get("currency", "$")), **factors))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/mm_doctor":
                path = data.get("path")
                if not path:
                    self._send(400, {"error": "missing 'path'"})
                    return
                try:
                    self._send(200, service.mm_doctor(
                        path, data.get("host"), rv.require_port(data)))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/bed_fit":
                path = data.get("path")
                if not path:
                    self._send(400, {"error": "missing 'path'"})
                    return
                try:
                    self._send(200, service.bed_fit(
                        path, data.get("host"), rv.require_port(data)))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/predict_success":
                path = data.get("path")
                if not path:
                    self._send(400, {"error": "missing 'path'"})
                    return
                try:
                    self._send(200, service.predict_success(
                        path, data.get("host"), rv.require_port(data)))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/community_knowledge":
                try:
                    self._send(200, service.community_knowledge(
                        str(data.get("query", "")), data.get("risks")))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/plate_export":
                try:
                    path = rv.require_path_string(data)
                    ui_plate = rv.require_int(data, "ui_plate")
                    from_f = rv.require_int(data, "from_filament")
                    to_f = rv.require_int(data, "to_filament")
                    out_path = rv.optional_str(data, "out_path", "") or None
                    self._send(200, service.plate_export(path, ui_plate, from_f, to_f, out_path))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/plate_dry_run":
                try:
                    path = rv.require_path_string(data)
                    ui_plate = rv.require_int(data, "ui_plate")
                    from_f = rv.require_int(data, "from_filament")
                    to_f = rv.require_int(data, "to_filament")
                    self._send(200, service.plate_dry_run(path, ui_plate, from_f, to_f))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/plate_inspect":
                path = data.get("path")
                if not path:
                    self._send(400, {"error": "missing 'path'"})
                    return
                try:
                    self._send(200, service.plate_inspect(path))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/demo_report":
                try:
                    self._send(200, service.demo_report())
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/intelligence_report":
                path = data.get("path")
                if not path:
                    self._send(400, {"error": "missing 'path'"})
                    return
                try:
                    factor_keys = ("price_per_kg", "power_w", "electricity_per_kwh",
                                   "machine_price", "machine_life_hours", "labor_hours",
                                   "labor_rate", "failure_rate_pct", "markup_pct",
                                   "marketplace_fee_pct", "grams_override", "print_hours",
                                   "packaging", "shipping_cost", "shipping_charged",
                                   "material_density")
                    factors = {k: rv.optional_float(data, k, 0.0) for k in factor_keys if data.get(k) is not None}
                    self._send(200, service.intelligence_report(
                        path, data.get("host"), data.get("filename"),
                        rv.require_port(data), str(data.get("currency", "$")),
                        **factors))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path in ("/pricing_doctor", "/profit_doctor"):
                path = data.get("path")
                if not path:
                    self._send(400, {"error": "missing 'path'"})
                    return
                try:
                    factor_keys = ("price_per_kg", "power_w", "electricity_per_kwh",
                                   "machine_price", "machine_life_hours", "labor_hours",
                                   "labor_rate", "failure_rate_pct", "markup_pct",
                                   "marketplace_fee_pct", "grams_override", "print_hours",
                                   "packaging", "shipping_cost", "shipping_charged",
                                   "material_density")
                    factors = {k: rv.optional_float(data, k, 0.0) for k in factor_keys if data.get(k) is not None}
                    common = dict(host=data.get("host"), filename=data.get("filename"),
                                  port=rv.require_port(data),
                                  currency=rv.optional_str(data, "currency", "$"))
                    if self.path == "/pricing_doctor":
                        self._send(200, service.pricing_doctor(path, **common, **factors))
                    else:
                        self._send(200, service.profit_doctor(
                            path, **common,
                            prints_per_month=rv.optional_int(data, "prints_per_month", 20),
                            fixed_cost=data.get("fixed_cost"),
                            batch_count=rv.optional_int(data, "batch_count", 10), **factors))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/cost_to_price":
                path = data.get("path")
                if not path:
                    self._send(400, {"error": "missing 'path'"})
                    return
                try:
                    factor_keys = ("price_per_kg", "power_w", "electricity_per_kwh",
                                   "machine_price", "machine_life_hours", "labor_hours",
                                   "labor_rate", "failure_rate_pct", "markup_pct",
                                   "marketplace_fee_pct", "grams_override", "print_hours",
                                   "packaging", "shipping_cost", "shipping_charged",
                                   "material_density")
                    factors = {k: rv.optional_float(data, k, 0.0) for k in factor_keys if data.get(k) is not None}
                    self._send(200, service.cost_to_price(
                        path, data.get("host"), data.get("filename"),
                        rv.require_port(data), rv.optional_str(data, "currency", "$"),
                        **factors))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/printer/capabilities":
                host = data.get("host")
                if not host:
                    self._send(400, {"error": "missing 'host'"})
                    return
                try:
                    self._send(200, service.printer_capabilities(host, rv.require_port(data)))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/printer/firmware":
                host = data.get("host")
                if not host:
                    self._send(400, {"error": "missing 'host'"})
                    return
                try:
                    self._send(200, service.printer_firmware(host, rv.require_port(data)))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/printer/health":
                host = data.get("host")
                if not host:
                    self._send(400, {"error": "missing 'host'"})
                    return
                try:
                    self._send(200, service.printer_health(host, rv.require_port(data), int(data.get("limit", 50))))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/printer/failure_insights":
                host = data.get("host")
                if not host:
                    self._send(400, {"error": "missing 'host'"})
                    return
                try:
                    self._send(200, service.printer_failure_insights(host, rv.require_port(data), int(data.get("limit", 50))))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/library":
                try:
                    self._send(200, service.library_list(
                        data.get("query", ""), data.get("tag")))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/library/delete":
                pid = data.get("id")
                if pid is None:
                    self._send(400, {"error": "missing 'id'"})
                    return
                try:
                    self._send(200, service.library_delete(pid))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/history":
                pid = data.get("project_id")
                if pid is None:
                    self._send(400, {"error": "missing 'project_id'"})
                    return
                try:
                    self._send(200, service.library_history(pid))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/batch":
                paths = data.get("paths")
                if not paths or not isinstance(paths, list):
                    self._send(400, {"error": "missing 'paths' (non-empty list)"})
                    return
                try:
                    self._send(200, service.batch_start(paths, data.get("out_dir")))
                except ValidationError as e:
                    self._send(400, {"error": str(e)})
                except Exception:
                    self._send(500, {"error": "internal error"})
            elif self.path == "/batch/status":
                job_id = data.get("job_id")
                if not job_id:
                    self._send(400, {"error": "missing 'job_id'"})
                    return
                status = service.batch_status(job_id)
                if status is None:
                    self._send(404, {"error": "unknown job"})
                else:
                    self._send(200, status)
            elif self.path == "/shutdown":
                # Graceful half of the L4 zero-orphan sequence (see
                # sidecar::shutdown_sidecar): reply first, THEN stop the
                # server from a separate thread — ThreadingHTTPServer runs
                # each request in its own thread, so calling shutdown() here
                # (a different thread from the one blocked in
                # serve_forever()) is the documented safe way to do this, not
                # a deadlock risk. Once serve_forever() returns, serve()
                # falls through and the process exits on its own.
                self._send(200, {"ok": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            else:
                self._send(404, {"error": "not found"})

    return Handler


#: Ports to fall back on when the operating system will not hand out an ephemeral
#: one. They sit below the Windows dynamic range (49152-65535), so they are still
#: available on a machine whose dynamic range is exhausted — which is not a rare
#: state: one developer machine here had 14,000 sockets held open by Docker
#: Desktop, and the loopback service could not bind at all. Studio then does not
#: start, for a reason that has nothing to do with Studio.
FALLBACK_PORTS = (38731, 38732, 38733, 38734, 38735)


def build_server(host: str = "127.0.0.1", port: int = 0, attempts: int = 4):
    """Return (httpd, token). Caller runs httpd.serve_forever().

    Asking for port 0 lets the operating system choose, which is right and is what
    this does first. When it refuses — because nothing is free in the dynamic
    range — a handful of fixed ports below that range are tried rather than
    failing the launch outright.
    """
    token = secrets.token_hex(16)
    last: OSError | None = None

    for attempt in range(max(1, attempts)):
        try:
            return ThreadingHTTPServer((host, port), _make_handler(token)), token
        except OSError as exc:
            last = exc
            if port != 0:
                break
            time.sleep(0.25 * (attempt + 1))

    if port == 0:
        for fallback in FALLBACK_PORTS:
            try:
                return ThreadingHTTPServer((host, fallback), _make_handler(token)), token
            except OSError as exc:
                last = exc

    raise OSError(
        f"this machine would not give Studio a port to listen on ({last}). Something "
        "is holding a very large number of network connections open — Docker, a VPN "
        "or a download manager are the usual causes. Closing it and starting Studio "
        "again is enough.") from last


def serve(host: str = "127.0.0.1", port: int = 0) -> None:
    _watch_parent_then_exit()
    _lifeline.start_parent_lifeline()
    httpd, token = build_server(host, port)
    actual_port = httpd.server_address[1]
    print(json.dumps({"port": actual_port, "token": token}), flush=True)  # handshake line
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
