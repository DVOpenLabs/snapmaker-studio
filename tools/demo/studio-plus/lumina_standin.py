"""Run Studio's loopback Lumina-compatible STAND-IN until you press Ctrl+C. It is a hand-written test double, not Lumina.

Usage:  python -I tools/demo/studio-plus/lumina_standin.py

Prints one JSON line with its 127.0.0.1 URL (an ephemeral port). Paste that URL into Studio's "Lumina service" page. It serves
synthetic artifacts only and listens on loopback only.
"""
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
from tests.mocks.lumina_server import LuminaHttpMock  # noqa: E402

with LuminaHttpMock() as mock:
    print(json.dumps({"url": mock.url}), flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
