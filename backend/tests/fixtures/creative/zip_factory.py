"""Small synthetic 3MF ZIP builder used by creative reader contract tests."""
from __future__ import annotations

import io
import json
import zipfile

CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"


def model_xml(*, namespace: str = CORE) -> bytes:
    return f'<model xmlns="{namespace}" unit="millimeter"><resources/><build/></model>'.encode()


def make_3mf(*, settings: dict | None = None, members: dict[str, bytes] | None = None,
             model: bytes | None = None, duplicate: tuple[str, bytes, bytes] | None = None,
             compression: int = zipfile.ZIP_DEFLATED) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=compression) as archive:
        archive.writestr("3D/3dmodel.model", model if model is not None else model_xml())
        if settings is not None:
            archive.writestr("Metadata/project_settings.config", json.dumps(settings).encode())
        for name, value in (members or {}).items():
            archive.writestr(name, value)
        if duplicate is not None:
            name, first, second = duplicate
            archive.writestr(name, first)
            archive.writestr(name, second)
    return output.getvalue()
