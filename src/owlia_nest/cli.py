"""owlia-nest CLI — install, configure, and serve."""

import argparse
import os
import sys
from pathlib import Path
from .server import serve, load_config, save_config


def _detect_workspace():
    """Detect OpenClaw workspace path. Returns expanded Path."""
    import subprocess
    try:
        out = subprocess.run(
            ["openclaw", "config", "get", "agents.defaults.workspace"],
            capture_output=True, text=True, timeout=5
        )
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip()).expanduser().resolve()
    except Exception:
        pass
    # Legacy fallbacks
    for candidate in [Path.home() / "clawd", Path.home() / ".openclaw" / "workspace"]:
        if candidate.exists():
            return candidate
    return Path.home() / ".openclaw" / "workspace"


def cmd_init(args):
    """Create default config if not present."""
    ws = _detect_workspace()
    print(f"🔍 Detected workspace: {ws}")
    default_dirs = [
        str(ws / "docs"),
        str(ws / "memory"),
        str(ws),
    ]
    existing = [d for d in default_dirs if Path(d).expanduser().exists()]
    config_path = Path.home() / ".config" / "owlia-nest" / "dirs.json"
    if config_path.exists():
        print(f"Config already exists: {config_path}")
        print("Use `owlia-nest add <dir>` to add directories.")
        return
    dir_paths = [Path(d).expanduser().resolve() for d in existing]
    saved = save_config(dir_paths)
    print(f"✅ Created {saved}")
    for d in dir_paths:
        print(f"   📂 {d}")


def cmd_add(args):
    """Add a directory to monitor."""
    target = Path(args.dir).expanduser().resolve()
    if not target.exists():
        print(f"❌ Directory does not exist: {target}")
        sys.exit(1)
    config_path = Path.home() / ".config" / "owlia-nest" / "dirs.json"
    if not config_path.exists():
        dirs = []
    else:
        data = load_config()
        dirs = data
    # load_config returns resolved Paths; check via string equality
    dir_strs = [str(d) for d in dirs]
    if str(target) in dir_strs:
        print(f"Already monitoring: {target}")
        return
    dirs.append(target)
    saved = save_config(dirs)
    print(f"✅ Added {target}")


def cmd_list(args):
    """List monitored directories."""
    dirs = load_config()
    config_path = Path.home() / ".config" / "owlia-nest" / "dirs.json"
    print(f"Config: {config_path}")
    print(f"Monitored directories ({len(dirs)}):")
    for d in dirs:
        status = "✅" if d.exists() else "❌"
        print(f"  {status} {d}")


def cmd_serve(args):
    """Start the docs server."""
    dirs = load_config()
    prefix = args.prefix or ""
    serve(host=args.host, port=args.port, prefix=prefix, targets=dirs)


def cmd_setup(args):
    """Auto-configure everything: init config, detect Caddy, generate configs."""
    print("🦉 Owlia Docs Setup\n")

    # Step 1: init
    config_path = Path.home() / ".config" / "owlia-nest" / "dirs.json"
    if not config_path.exists():
        cmd_init(None)
    else:
        print("📋 Config already exists, skipping init.")
    print()

    # Step 2: check for Caddy
    caddy_path = None
    for p in ["/opt/homebrew/bin/caddy", "/usr/local/bin/caddy", "/usr/bin/caddy"]:
        if Path(p).exists():
            caddy_path = p
            break
    if caddy_path:
        print(f"✅ Found Caddy: {caddy_path}")
    else:
        caddy_path = "caddy"
        print("⚠️  Caddy not found in common paths. Install it:")
        print("   brew install caddy  (macOS)")
        print("   apt install caddy   (Debian/Ubuntu)")
        print("   Server will run without reverse proxy on :8788")

    # Step 3: detect platform
    platform = "macos" if sys.platform == "darwin" else "linux"
    print(f"🖥  Platform: {platform}")

    if platform == "macos":
        # Generate launchd plist
        plist_path = Path.home() / "Library" / "LaunchAgents" / "com.owlia.docs.plist"
        plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.owlia.docs</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>-m</string>
        <string>owlia_nest</string>
        <string>serve</string>
        <string>--port</string>
        <string>8788</string>
        <string>--host</string>
        <string>127.0.0.1</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/owlia-nest.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/owlia-nest.err</string>
</dict>
</plist>"""
        plist_path.parent.mkdir(parents=True, exist_ok=True)
        plist_path.write_text(plist)
        print(f"✅ Created launchd service: {plist_path}")

        # Caddyfile
        caddyfile = f""":80 {{
    handle /docs* {{
        reverse_proxy localhost:8788
    }}
    respond "🦉 Owlia Docs → http://localhost/docs/" 200
}}"""
        caddy_dir = Path.home() / ".config" / "owlia-nest"
        caddy_path = caddy_dir / "Caddyfile"
        caddy_path.write_text(caddyfile)
        print(f"✅ Created Caddy config: {caddy_path}")

        print(f"""
🚀 To start:
   # 1. Start the server
   launchctl load {plist_path}

   # 2. Start Caddy (if you want reverse proxy on :80)
   caddy run --config {caddy_path}

   # Open
   open http://localhost/docs/
""")
    else:
        # Linux: systemd
        unit = """[Unit]
Description=Owlia Docs Server
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 -m owlia_nest serve --port 8788 --host 127.0.0.1
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
"""
        unit_path = Path.home() / ".config" / "systemd" / "user" / "owlia-nest.service"
        unit_path.parent.mkdir(parents=True, exist_ok=True)
        unit_path.write_text(unit)
        print(f"✅ Created systemd unit: {unit_path}")
        print(f"""
🚀 To start:
   systemctl --user enable --now owlia-nest
   # Then open http://localhost:8788/
""")


def main():
    parser = argparse.ArgumentParser(description="Owlia Docs — PA document browser")
    sub = parser.add_subparsers(dest="command")

    p_init = sub.add_parser("init", help="Create default config")
    p_init.set_defaults(func=cmd_init)

    p_add = sub.add_parser("add", help="Add a directory to monitor")
    p_add.add_argument("dir", help="Directory path")
    p_add.set_defaults(func=cmd_add)

    p_list = sub.add_parser("list", help="List monitored directories")
    p_list.set_defaults(func=cmd_list)

    p_serve = sub.add_parser("serve", help="Start the docs server")
    p_serve.add_argument("--port", type=int, default=8788)
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--prefix", default="")
    p_serve.set_defaults(func=cmd_serve)

    p_setup = sub.add_parser("setup", help="Auto-configure everything")
    p_setup.set_defaults(func=cmd_setup)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return
    args.func(args)


if __name__ == "__main__":
    main()
