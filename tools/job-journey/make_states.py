"""Synthetic projects for the state captures: python make_states.py <out-dir>. Invented geometry only."""
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2] / "backend"
sys.path[:0] = [str(root), str(root / "tests")]
from scene_fixtures import big_grid_3mf, binary_stl, plain_cube_3mf  # noqa: E402

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
plain_cube_3mf(out / "inch-project.3mf", unit="inch")
plain_cube_3mf(out / "plain-project.3mf")
binary_stl(out / "shape-only.stl")
big_grid_3mf(out / "very-detailed.3mf", 150_000)
print("ok")
