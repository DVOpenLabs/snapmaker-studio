"""Calibration basis identity, palette comparison and local history."""
from __future__ import annotations

import json
import math
import time
from typing import Any

from snapstudio_core import material_plan
from snapstudio_core.foundation.decode import content_hash, revision_envelope
from snapstudio_core.foundation.store import open_store

_SCHEMA = """
CREATE TABLE IF NOT EXISTS calibration_basis (
  calibration_basis_id TEXT PRIMARY KEY,
  family TEXT NOT NULL,
  layer_height_mm REAL NOT NULL,
  nozzle_mm REAL NOT NULL,
  material TEXT NOT NULL,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS calibration_runs (
  run_id TEXT PRIMARY KEY,
  calibration_basis_id TEXT NOT NULL,
  inputs_revision TEXT NOT NULL,
  created_at REAL NOT NULL,
  payload_json TEXT NOT NULL,
  FOREIGN KEY(calibration_basis_id) REFERENCES calibration_basis(calibration_basis_id)
);
"""


def basis_document(family: str, layer_height_mm: float, nozzle_mm: float, material: str) -> dict:
    if family not in ("frontlit", "backlit"):
        raise ValueError("family must be frontlit or backlit")
    values = (layer_height_mm, nozzle_mm)
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in values):
        raise ValueError("layer height and nozzle must be positive finite numbers")
    normalized = {"family": family, "layer_height_mm": round(float(layer_height_mm), 4),
                  "nozzle_mm": round(float(nozzle_mm), 4), "material": material.strip().upper()}
    return {**normalized, "calibration_basis_id": "calibration-basis:" + content_hash(normalized).split(":", 1)[1]}


def evaluate(palette: dict, basis: dict, physical_colors: dict[str, str], owned_filaments: list[dict]) -> dict:
    entries = []
    for index, item in enumerate(palette["entries"]):
        physical = physical_colors.get(str(index))
        alternatives = []
        for spool in owned_filaments:
            color = spool.get("color") if isinstance(spool, dict) else None
            distance = material_plan.colour_distance(item["color"], color)
            if distance is not None:
                alternatives.append({"label": str(spool.get("label") or "Owned filament"),
                                     "color": color, "distance": round(distance, 1),
                                     "advisory": True})
        alternatives.sort(key=lambda alt: alt["distance"])
        entries.append({"label": item["label"], "simulated_color": item["color"],
                        "physical_color": physical, "physical_distance": material_plan.colour_distance(
                            item["color"], physical), "td": item["td"],
                        "td_provenance": item["td_provenance"], "alternatives": alternatives[:3]})
    return {"calibration_basis": basis, "entries": entries,
            "advisory": "Palette colours are simulated targets; physical readings are separate observations. Owned-filament matches are advisory."}


def save_run(basis: dict, palette: dict, result: dict, data_dir: str | None = None) -> dict:
    inputs_revision = revision_envelope({"calibration_basis_id": basis["calibration_basis_id"],
                                         "palette_hash": content_hash(palette),
                                         # physical readings and owned filaments change the comparison, so they
                                         # change the run identity; an earlier result is never overwritten
                                         "comparison_hash": content_hash(result["entries"])})
    run_id = inputs_revision["revision"]
    payload = {**result, "inputs_revision": inputs_revision}
    with open_store("calibration", _SCHEMA, 1, data_dir=data_dir) as conn:
        conn.execute("BEGIN IMMEDIATE")                     # the store connection is autocommit; keep both rows together
        try:
            conn.execute("INSERT OR IGNORE INTO calibration_basis VALUES (?, ?, ?, ?, ?, ?)",
                         (basis["calibration_basis_id"], basis["family"], basis["layer_height_mm"],
                          basis["nozzle_mm"], basis["material"], time.time()))
            conn.execute("INSERT OR IGNORE INTO calibration_runs VALUES (?, ?, ?, ?, ?)",
                         (run_id, basis["calibration_basis_id"], inputs_revision["revision"], time.time(),
                          json.dumps(payload, separators=(",", ":"))))
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    return {"run_id": run_id, **payload}


def history(data_dir: str | None = None) -> list[dict]:
    with open_store("calibration", _SCHEMA, 1, data_dir=data_dir) as conn:
        rows = conn.execute("SELECT payload_json FROM calibration_runs ORDER BY created_at DESC, run_id DESC LIMIT 50").fetchall()
    return [json.loads(row[0]) for row in rows]
