#!/usr/bin/env python3
"""E2E server launcher: isolated fixture tree + isolated config.

Starts two servers:
  :18800 prefix /docs — no auth (main flows)
  :18801 prefix ""    — token auth ("e2e-token")

Prints FIXTURE_ROOT=<path> then serves until killed. Nothing touches
~/.config/owlia-nest or .devdocs.
"""
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from owlia_nest.server import create_app  # noqa: E402

# 1x1 transparent PNG
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d4944415478da63fcffffff7f0005fe02fea72d224a0000000049454e44ae426082")


def build_fixtures(root: Path):
    (root / "README.md").write_text(
        "# Hello E2E\n\nbody text\n\n```python\ndef fenced():\n    return 1\n```\n"
        '\n<img src=x onerror="alert(1)">\n', encoding="utf-8")
    (root / "notes.txt").write_text("plain notes\nline two\n", encoding="utf-8")
    (root / "script.py").write_text('def main():\n    return "e2e"\n', encoding="utf-8")
    (root / "we & rd's.md").write_text("# Special chars survive\n", encoding="utf-8")
    (root / "img.png").write_bytes(PNG)
    deep = root / "深层" / "sub"
    deep.mkdir(parents=True)
    (deep / "deep-note.md").write_text("# Deep note\n", encoding="utf-8")


def main():
    base = Path(tempfile.mkdtemp(prefix="owlia-e2e-"))
    root = base / "docs"
    root.mkdir()
    build_fixtures(root)
    cfg1 = base / "config-main.json"
    cfg2 = base / "config-auth.json"

    h1 = create_app(([root], [], []), "/docs", ephemeral=True, config_path=cfg1)
    h2 = create_app(([root], [], []), "", ephemeral=True, auth_token="e2e-token",
                    config_path=cfg2)
    s1 = ThreadingHTTPServer(("127.0.0.1", 18800), h1)
    s2 = ThreadingHTTPServer(("127.0.0.1", 18801), h2)
    print(f"FIXTURE_ROOT={root}", flush=True)
    print("E2E servers: http://127.0.0.1:18800/docs/ (open), "
          "http://127.0.0.1:18801/ (token=e2e-token)", flush=True)
    threading.Thread(target=s2.serve_forever, daemon=True).start()
    s1.serve_forever()


if __name__ == "__main__":
    main()
