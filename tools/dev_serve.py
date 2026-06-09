#!/usr/bin/env python3
"""Local dev launcher: serve a docs dir directly (bypasses ~/.config)."""
import sys, os
from pathlib import Path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from owlia_nest.server import serve
raw = sys.argv[1:] or [str(Path(__file__).resolve().parent.parent / ".devdocs")]
targets = [Path(p).expanduser().resolve() for p in raw]
print("DEV_SERVE targets:", targets, flush=True)
serve(host="127.0.0.1", port=8788, prefix="/docs", targets=targets)
