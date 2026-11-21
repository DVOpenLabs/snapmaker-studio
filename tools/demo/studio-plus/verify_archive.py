"""Compare a source 3MF with a Studio-prepared copy. Read-only. Usage: python -I verify_archive.py SOURCE OUTPUT"""
import hashlib, json, re, sys, zipfile

src, out = sys.argv[1], sys.argv[2]


def members(path):
    with zipfile.ZipFile(path) as z:
        bad = z.testzip()
        return bad, {n: z.read(n) for n in z.namelist() if not n.endswith("/")}


def stats(blobs):
    models = {n: b.decode("utf-8", "replace") for n, b in blobs.items() if n.endswith(".model")}
    return {
        "model_parts": sorted(models),
        "paint_color_attrs": sum(len(re.findall(r'(?:paint_color|mmu_segmentation|slic3rpe:mmu_segmentation)="', t)) for t in models.values()),
        "triangles": sum(len(re.findall(r"<triangle[\s/]", t)) for t in models.values()),
        "objects": sum(len(re.findall(r"<object[\s/>]", t)) for t in models.values()),
        "components": sum(len(re.findall(r"<component[\s/]", t)) for t in models.values()),
        "extruder_assignments": sorted(set(re.findall(r'key="extruder"\s+value="(\d+)"', blobs.get("Metadata/model_settings.config", b"").decode("utf-8", "replace")))),
        "has_project_settings": "Metadata/project_settings.config" in blobs,
    }


bad_s, a = members(src)
bad_o, b = members(out)
same = sorted(n for n in a if n in b and a[n] == b[n])
changed = sorted(n for n in a if n in b and a[n] != b[n])
dropped = sorted(n for n in a if n not in b)
added = sorted(n for n in b if n not in a)
print(json.dumps({
    "source_zip_ok": bad_s is None, "output_zip_ok": bad_o is None,
    "source_sha256": hashlib.sha256(open(src, "rb").read()).hexdigest(),
    "output_sha256": hashlib.sha256(open(out, "rb").read()).hexdigest(),
    "members_source": len(a), "members_output": len(b),
    "identical": same, "changed": changed, "dropped": dropped, "added": added,
    "mesh_parts_identical": all(a[n] == b.get(n) for n in a if n.endswith(".model") and n != "3D/3dmodel.model"),
    "source_stats": stats(a), "output_stats": stats(b),
}, indent=1))
try:
    sa, sb = json.loads(a["Metadata/project_settings.config"]), json.loads(b["Metadata/project_settings.config"])
    diff = {k: [str(sa.get(k))[:60], str(sb.get(k))[:60]] for k in sorted(set(sa) | set(sb)) if sa.get(k) != sb.get(k)}
    print("SETTINGS_DIFF", json.dumps({"keys_changed": len(diff), "sample": dict(list(diff.items())[:25])}))
except Exception as e:
    print("SETTINGS_DIFF", json.dumps({"error": str(e)[:80]}))
