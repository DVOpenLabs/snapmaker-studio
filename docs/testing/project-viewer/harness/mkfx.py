import sys
from pathlib import Path
import os, tempfile
ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "backend"))
from tests import scene_fixtures as fx
out = Path(os.environ.get("P3B_FIXTURES", Path(tempfile.gettempdir()) / "p3b-fixtures"))
out.mkdir(parents=True, exist_ok=True)
fx.big_grid_3mf(out / "grid-100k.3mf", 100_000)
fx.bambu_project(out / "three-roles.3mf", parts=3, items=[("100", fx.tf(60, 80, 0))], plates=[(1, [("100", 0)])],
                 roles=["normal_part", "modifier_part", "negative_part"])
fx.bambu_project(out / "two-plates.3mf", parts=1, items=[("100", fx.tf(60, 80, 0)), ("100", fx.tf(150, 80, 0))],
                 plates=[(1, [("100", 0)]), (2, [("100", 1)])])
fx.plain_cube_3mf(out / "inch-cube.3mf", size=1.0, unit="inch", at=(2.0, 2.0, 0.0))
print("ok")
