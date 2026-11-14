"""Write the disposable synthetic inputs used by the Studio+ demo journeys into an EMPTY folder you choose.

Usage:  python -I tools/demo/studio-plus/make_samples.py <empty-folder>

Every file is generated here from Studio's own test helper (backend/tests/fixtures/creative/zip_factory.py), built from
the documented output shapes of the creative tools. They are SYNTHETIC: not captured from any real tool, not real
projects, and the "image" and "G-code" are placeholder text, not a picture or slicer output. Nothing outside the folder
you pass is touched.
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend" / "tests" / "fixtures" / "creative"))
from zip_factory import make_3mf, make_ditherforge, make_ditherforge_bambu, make_kromacut  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    d = pathlib.Path(sys.argv[1])
    d.mkdir(parents=True, exist_ok=True)
    if any(d.iterdir()):
        print(f"refusing: {d} is not empty")
        return 2
    (d / "sample-kromacut.3mf").write_bytes(make_kromacut())
    (d / "sample-ditherforge-bambu.3mf").write_bytes(make_ditherforge_bambu(extra={"Metadata/plate_1.json": b"{}"}))
    (d / "sample-ditherforge-generic.3mf").write_bytes(make_ditherforge(extra={"Metadata/plate_1.json": b"{}"}))
    (d / "sample-plain.3mf").write_bytes(make_3mf(settings={"layer_height": "0.2"}, members={"Metadata/custom.bin": b"synthetic-opaque"}))
    (d / "synthetic-image.png").write_bytes(b"synthetic-image-bytes-not-a-real-picture")
    (d / "synthetic-sliced.gcode").write_text("; synthetic sliced stand-in, not produced by any slicer\n")
    print("wrote", ", ".join(sorted(p.name for p in d.iterdir())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
