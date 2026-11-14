"""The installed-build acceptance harness's generated painted project must be a valid 3MF package.

`tools/acceptance/run.ps1` builds one small painted project at run time. When Prepare's readability rule began to
require the package's own parts (`[Content_Types].xml`, `_rels/.rels`), that file, which had only the model and two
config parts, became "not a project" and the harness's painted-colour route check failed against a healthy build.
This reads the fixture's text straight out of the harness, so a future edit cannot drift from what is tested here.
"""
from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

from snapstudio_core import eligibility, project_traits
from snapstudio_core.container import ThreeMF

RUN = Path(__file__).resolve().parents[2] / "tools" / "acceptance" / "run.ps1"


def _here_string(name: str) -> str:
    text = RUN.read_text(encoding="utf-8")
    found = re.search(r"\$" + name + r" = @'\r?\n(.*?)\r?\n'@", text, re.S)
    assert found, f"{name} is not defined in the harness"
    return found.group(1).strip()


def _entries() -> dict[str, str]:
    """The entries the harness writes, by name, exactly as its zip loop lists them."""
    text = RUN.read_text(encoding="utf-8")
    loop = re.search(r'\$zip = \[System\.IO\.Compression\.ZipFile\]::Open\(\$paintedWork.*?foreach \(\$entry in @\((.*?)\)\) \{',
                     text, re.S)
    assert loop, "the painted-project zip loop was not found"
    pairs = re.findall(r'name = "([^"]+)"; body = \$(\w+)', loop.group(1))
    assert pairs, "no entries found in the painted-project zip loop"
    return {name: _here_string(var) for name, var in pairs}


def _write(tmp_path, entries: dict[str, str], name: str) -> str:
    path = tmp_path / name
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for entry, body in entries.items():
            z.writestr(entry, body)
    return str(path)


def test_the_harness_painted_project_is_a_readable_package(tmp_path):
    entries = _entries()
    assert {"[Content_Types].xml", "_rels/.rels", "3D/3dmodel.model"} <= set(entries)
    path = _write(tmp_path, entries, "painted.3mf")
    assert eligibility.is_readable(ThreeMF.open(path))
    traits = project_traits.extract(path)
    assert traits["readable"] is True
    assert traits["has_painted_color"]["value"] is True      # the assertion the harness's route check makes


def test_the_original_package_without_its_required_parts_is_refused(tmp_path):
    original = {k: v for k, v in _entries().items() if k not in ("[Content_Types].xml", "_rels/.rels")}
    path = _write(tmp_path, original, "malformed.3mf")
    assert not eligibility.is_readable(ThreeMF.open(path))
    traits = project_traits.extract(path)
    assert traits["readable"] is False
    assert traits["has_painted_color"]["value"] is None
