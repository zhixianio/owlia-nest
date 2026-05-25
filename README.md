# 🦉 owlia-nest

A self-hosted Markdown document browser for OpenClaw PA outputs.
Browse your PA's research, analysis, and session logs with beautiful
rendering, themes, and PWA support.

## Quick Start

```bash
pip install owlia-nest
owlia-nest init
owlia-nest serve
# Open http://localhost:8788/
```

## Features

- **📂 Auto-scan** directories for Markdown, code, and config files
- **🕐 Recent-first** sorting by modification time
- **🏷️ Category tabs** — Documents, Code, Config, Directories
- **🎨 5 themes** — GitHub Light/Dark, Nord, Dracula, Solarized
- **📱 PWA** — Add to Home Screen on mobile
- **🔄 Auto-start** — launchd (macOS) / systemd (Linux)
- **🔀 Reverse proxy** — Caddy integration for clean URLs

## Commands

| Command | Description |
|---------|-------------|
| `owlia-nest init` | Create default config, detect existing dirs |
| `owlia-nest add <dir>` | Add a directory to monitor |
| `owlia-nest list` | List monitored directories |
| `owlia-nest serve` | Start the HTTP server |
| `owlia-nest setup` | Full auto-config (Caddy + auto-start) |

## For OpenClaw PA

See [`skills/owlia-nest/SKILL.md`](skills/owlia-nest/SKILL.md) for PA installation instructions.

## Requirements

- Python ≥ 3.9
- `markdown`, `pygments`
- Optional: [Caddy](https://caddyserver.com/) for reverse proxy on port 80

## License

MIT
