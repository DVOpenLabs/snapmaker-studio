"""Benchmark and budget-coverage report for scene/1.

    py -3.13 backend/tools/scene_benchmark.py --out docs/testing/scene-contract/results.json \
        [--real-world DIR] [--local-root DIR ...] [--local-sample 5]

Measures, per corpus item: whether it fits the budgets, parse+encode time (cold and warm best-of-N),
peak extra memory (tracemalloc peak AND a sampled working-set delta), response size and counts. Then the
hard gates (100k-triangle fixture, cancel latency, 50-cycle leak check) and the coverage fraction.

Privacy: items from outside the repository (``--local-root``) are recorded ONLY as anonymized ids
``P-01..P-05`` with byte size and triangle count. Names, paths and contents are never written. Nothing
here modifies any input; every file is only read.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
import tempfile
import threading
import time
import tracemalloc
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
REPO = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from snapstudio_core import scene, scene_limits as L  # noqa: E402
from tests import scene_fixtures as fx  # noqa: E402

MIB = 1024 * 1024


def rss_bytes() -> int:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
        k32 = ctypes.WinDLL("kernel32")
        psapi = ctypes.WinDLL("psapi")
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
        counters = PMC()
        counters.cb = ctypes.sizeof(PMC)
        psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
        return int(counters.WorkingSetSize)
    with open("/proc/self/statm") as fh:
        return int(fh.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")


def machine() -> dict:
    total = None
    try:
        if sys.platform == "win32":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("l", ctypes.c_ulong), ("m", ctypes.c_ulong), ("tp", ctypes.c_ulonglong), ("ap", ctypes.c_ulonglong),
                            ("tpf", ctypes.c_ulonglong), ("apf", ctypes.c_ulonglong), ("tv", ctypes.c_ulonglong),
                            ("av", ctypes.c_ulonglong), ("ae", ctypes.c_ulonglong)]
            ms = MS()
            ms.l = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
            total = ms.tp
        else:
            total = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    except Exception:  # noqa: BLE001
        pass
    return {"platform": platform.platform(), "python": platform.python_version(), "cpu_count": os.cpu_count(),
            "processor": platform.processor() or None, "ram_gib": round(total / 1024 ** 3, 1) if total else None}


class Sampler(threading.Thread):
    """Samples the working set while a measurement runs."""

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.stop = threading.Event()
        self.peak = 0

    def run(self) -> None:
        while not self.stop.is_set():
            self.peak = max(self.peak, rss_bytes())
            time.sleep(0.005)


LIFTED = {"MAX_PARSED_TRIANGLES": 2_000_000, "MAX_VERTICES": 2_000_000, "MAX_RENDERED_TRIANGLES": 2_000_000,
          "MAX_RESPONSE_BYTES": 256 * MIB, "MODEL_XML_BYTES": 512 * MIB, "ARCHIVE_EXPANSION_BYTES": 1024 * MIB,
          "MAX_NODES": 50_000}


def lifted(path: str) -> dict:
    """Evidence for a budget decision: what the refused file would cost if the budgets were raised
    (to 2M triangles / 256 MiB). Reports what it measures; never ships those numbers as limits."""
    saved = {k: getattr(L, k) for k in LIFTED}
    try:
        for k, v in LIFTED.items():
            setattr(L, k, v)
        t = time.perf_counter()
        try:
            sc = scene.build_scene_dict(path, "0" * 64)
            body = scene.serialize(sc)
        except scene.SceneError as exc:
            return {"still_refused": exc.code, "message": exc.message}
        return {"triangles": sc["counts"]["triangles"], "rendered_triangles": sc["counts"]["rendered_triangles"],
                "vertices": sc["counts"]["vertices"], "nodes": sc["counts"]["nodes"], "response_bytes": len(body),
                "time_s": round(time.perf_counter() - t, 2)}
    finally:
        for k, v in saved.items():
            setattr(L, k, v)


def measure(path: str, warm_runs: int) -> dict:
    size = os.path.getsize(path)
    rec: dict = {"bytes": size}
    ceiling = size > L.SNAPSHOT_MAX_BYTES
    rec["job_gate"] = "SNAPSHOT_CEILING" if ceiling else "ok"
    try:
        t = time.perf_counter()
        body = scene.build_scene(path, "0" * 64)
        cold = time.perf_counter() - t
    except scene.SceneError as exc:
        rec.update(result="refused", code=exc.code, message=exc.message, fits_budgets=False)
        rec["lifted"] = lifted(path)
        return rec
    sc = json.loads(body)
    rec.update(result="ok", code=None, status=sc["status"], fits_budgets=not ceiling,
               triangles=sc["counts"]["triangles"], rendered_triangles=sc["counts"]["rendered_triangles"],
               vertices=sc["counts"]["vertices"], nodes=sc["counts"]["nodes"], meshes=sc["counts"]["meshes"],
               response_bytes=len(body), limitations=[l["code"] for l in sc["limitations"]],
               cold_s=round(cold, 3))
    times = []
    for _ in range(warm_runs):
        t = time.perf_counter()
        scene.build_scene(path, "0" * 64)
        times.append(time.perf_counter() - t)
    rec["warm_best_s"] = round(min(times), 3)
    rec["warm_median_s"] = round(statistics.median(times), 3)
    base = rss_bytes()
    sampler = Sampler()
    sampler.start()
    tracemalloc.start()
    scene.build_scene(path, "0" * 64)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    sampler.stop.set()
    sampler.join()
    rec["tracemalloc_peak_mib"] = round(peak / MIB, 1)
    rec["rss_delta_mib"] = round(max(0, sampler.peak - base) / MIB, 1)
    return rec


def corpus(tmp: Path, args) -> list[tuple[str, str, str]]:
    """(id, class, path). Synthetic fixtures are authored here; nothing private is named."""
    items: list[tuple[str, str, str]] = []
    items.append(("S-cube", "synthetic", str(fx.plain_cube_3mf(tmp / "s-cube.3mf"))))
    items.append(("S-bambu-3parts", "synthetic", str(fx.bambu_project(
        tmp / "s-bambu.3mf", parts=3, items=[("100", fx.tf(10, 10, 0))], plates=[(1, [("100", 0)])],
        roles=["normal_part", "modifier_part", "negative_part"]))))
    items.append(("S-prusa-volumes", "synthetic", str(fx.prusa_project(
        tmp / "s-prusa.3mf", volumes=[(0, 11, "ModelPart"), (12, 23, "ParameterModifier")]))))
    items.append(("S-stl", "synthetic", str(fx.binary_stl(tmp / "s.stl"))))
    for n in (10_000, 50_000, 100_000):
        items.append((f"S-grid-{n // 1000}k", "synthetic", str(fx.big_grid_3mf(tmp / f"s-grid-{n}.3mf", n))))
    root = fx.model_xml([fx.cube_object("1", 10)], [("1", fx.tf(i * 12.0 % 250, (i // 20) * 12.0, 0)) for i in range(300)])
    items.append(("S-instances-300", "synthetic", str(fx.three_mf(tmp / "s-inst.3mf", root))))
    items.append(("S-over-budget", "synthetic-over-budget", str(fx.big_grid_3mf(tmp / "s-over.3mf", 280_000))))
    for p in sorted((REPO / "examples").iterdir()):
        if p.suffix.lower() in (".3mf", ".stl") and ".orig." not in p.name:
            items.append((f"E-{p.stem}", "repo-example", str(p)))
    rw = Path(args.real_world) if args.real_world else BACKEND / "tests" / "fixtures" / "real-world"
    if rw.is_dir():
        for p in sorted(rw.glob("*.3mf")):
            if ".orig." not in p.name:
                items.append((f"R-{p.stem}", "real-world", str(p)))
    pool = sorted((p for d in args.local_root or [] for p in Path(d).rglob("*")
                   if p.suffix.lower() in (".3mf", ".stl") and p.is_file()),
                  key=lambda p: (p.stat().st_size, str(p)))
    if pool:   # evenly spaced by size across ALL local roots; only the anonymized id is ever recorded
        picks = [pool[int(i * (len(pool) - 1) / max(1, args.local_sample - 1))] for i in range(args.local_sample)]
        for n, p in enumerate(dict.fromkeys(picks), 1):
            items.append((f"P-{n:02d}", "local-anonymized", str(p)))
    return items


def survey(roots: list[str]) -> dict:
    """Size-only survey of local projects (no names): how many are over the snapshot ceiling."""
    sizes = []
    for d in roots:
        for p in Path(d).rglob("*"):
            if p.suffix.lower() == ".3mf" and p.is_file():
                sizes.append(p.stat().st_size)
    if not sizes:
        return {}
    over = sum(1 for s in sizes if s > L.SNAPSHOT_MAX_BYTES)
    sizes.sort()
    return {"files": len(sizes), "over_snapshot_ceiling": over, "fraction_within_ceiling": round(1 - over / len(sizes), 3),
            "median_mib": round(statistics.median(sizes) / MIB, 1), "p90_mib": round(sizes[int(0.9 * (len(sizes) - 1))] / MIB, 1)}


def gates(tmp: Path) -> dict:
    sys.path.insert(0, str(BACKEND))
    from snapstudio_api import scene_jobs as sj

    out: dict = {}
    big = fx.big_grid_3mf(tmp / "gate-100k.3mf", 100_000)
    m = measure(str(big), 3)
    out["fixture_100k_triangles"] = {"parse_encode_warm_s": m.get("warm_best_s"), "cold_s": m.get("cold_s"),
                                    "extra_peak_mib_tracemalloc": m.get("tracemalloc_peak_mib"),
                                    "extra_peak_mib_rss": m.get("rss_delta_mib"), "response_bytes": m.get("response_bytes"),
                                    "gate_time_le_10s": (m.get("warm_best_s") or 1e9) <= 10,
                                    "gate_mem_le_500mib": max(m.get("tracemalloc_peak_mib") or 0, m.get("rss_delta_mib") or 0) <= 500,
                                    "target_time_le_3s": (m.get("warm_best_s") or 1e9) <= 3,
                                    "target_mem_le_300mib": max(m.get("tracemalloc_peak_mib") or 0, m.get("rss_delta_mib") or 0) <= 300,
                                    "gate_response_le_8mib": (m.get("response_bytes") or 1e9) <= L.MAX_RESPONSE_BYTES}
    jobs = sj.SceneJobs(snapshot_root=str(tmp / "snap"))
    latencies = []
    for _ in range(5):
        job = jobs.start(str(big), f"bench-cancel-{time.monotonic_ns()}")
        end = time.monotonic() + 10
        while time.monotonic() < end and jobs.status(job["job_id"])["stage"] not in ("parsing", "encoding"):
            time.sleep(0.005)
        time.sleep(0.15)
        t = time.perf_counter()
        jobs.cancel(job["job_id"])
        while jobs.worker_alive():
            time.sleep(0.002)
        latencies.append(time.perf_counter() - t)
    out["cancel_latency_s"] = {"max": round(max(latencies), 3), "median": round(statistics.median(latencies), 3),
                               "gate_le_2s": max(latencies) <= 2.0}
    small = str(fx.plain_cube_3mf(tmp / "leak-small.3mf"))
    mid = str(fx.big_grid_3mf(tmp / "leak-mid.3mf", 20_000))
    base_threads = threading.active_count()
    wedged = False
    leak = sj.SceneJobs(snapshot_root=str(tmp / "snap2"))
    for i in range(50):
        job = leak.start(mid if i % 2 else small, f"bench-leak-{i:04d}-{time.monotonic_ns()}")
        if i % 3 == 0:
            time.sleep(0.01)
        leak.cancel(job["job_id"])
        wedged = wedged or leak.wedged()
    leak.close()
    end = time.monotonic() + 10
    while leak.worker_alive() and time.monotonic() < end:
        time.sleep(0.01)
    snaps = os.listdir(leak.snapshot_dir()) if leak.snapshot_dir() and os.path.isdir(leak.snapshot_dir()) else []
    out["leak_50_cycles"] = {"retained_jobs": leak.retained(), "cap": L.MAX_TERMINAL_JOBS, "temp_snapshots": len(snaps),
                             "threads_before": base_threads, "threads_after": threading.active_count(),
                             "worker_wedged_seen": wedged,
                             "gate_pass": leak.retained() <= L.MAX_TERMINAL_JOBS and not snaps
                             and threading.active_count() == base_threads and not wedged}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--real-world", help="folder holding the fetched real-world 3MF fixtures")
    ap.add_argument("--local-root", action="append", help="folder of local projects (anonymized ids only)")
    ap.add_argument("--local-sample", type=int, default=5)
    ap.add_argument("--warm-runs", type=int, default=3)
    args = ap.parse_args()
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        rows = []
        for ident, klass, path in corpus(tmp, args):
            rec = measure(path, args.warm_runs)
            rec.update(id=ident, **{"class": klass})
            rows.append(rec)
            print(f"{ident:24s} {klass:22s} {rec.get('result'):8s} {rec.get('code') or '':16s} "
                  f"{rec.get('warm_best_s', '-')!s:>7} s  {rec.get('response_bytes', '-')!s:>9} B", flush=True)
        results = {"schema": "scene-benchmark/1", "machine": machine(), "budgets": dict(L.LIMITS_ECHO),
                   "snapshot_ceiling_bytes": L.SNAPSHOT_MAX_BYTES, "items": rows}
        within = [r for r in rows if r["class"] in ("repo-example", "real-world", "local-anonymized", "synthetic")]
        results["coverage"] = {
            "by_class": {k: {"items": sum(1 for r in rows if r["class"] == k),
                             "fit": sum(1 for r in rows if r["class"] == k and r.get("fits_budgets"))}
                         for k in sorted({r["class"] for r in rows})},
            "fraction_fitting_excluding_deliberate_over_budget": round(
                sum(1 for r in within if r.get("fits_budgets")) / max(1, len(within)), 3)}
        if args.local_root:
            results["local_survey_3mf_sizes_only"] = survey(args.local_root)
        results["gates"] = gates(tmp)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
