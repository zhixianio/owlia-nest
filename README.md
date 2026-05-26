# 🦉 Owlia Nest

Self-hosted file browser for OpenClaw PA outputs. Browse your agent's research, analysis, and session logs on any device.

## Quick Start

One command, copy-paste:

```bash
pip install git+https://github.com/zhixianio/owlia-nest.git
```

Then start it pointing at your PA output directory:

```bash
owlia-nest ~/clawd/docs --port 8788 --prefix /docs
```

Open http://localhost:8788/docs

## Monitor Multiple Directories

```bash
owlia-nest ~/clawd/docs ~/other-project/output --port 8788 --prefix /docs
```

## Features

- 📂 Browse Markdown, code, config, images on any device
- 🎨 Dark/light theme + syntax highlighting (Pygments)
- 📱 PWA — add to home screen on iOS/Android
- 🔍 Search + category filters (doc/code/image/config/audio)
- 🚫 Exclude directories or file types from settings panel
- 🔄 One-click upgrade from settings (checks GitHub tags)
- 🔗 Works with Caddy/nginx reverse proxy + Tailscale

## Remote Access

For remote access (your PA server is on another machine):

1. Install [Tailscale](https://tailscale.com) on both machines
2. Run Owlia Nest on the PA machine
3. Access via `http://<tailscale-ip>:8788/docs` from any device
4. Add to home screen → PWA app on your phone

Or put it behind a reverse proxy (Caddy example):

```
your-domain.com {
    reverse_proxy 127.0.0.1:8788
}
```

## Auto-Start (macOS)

```bash
cat > ~/Library/LaunchAgents/com.owlia.nest.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.owlia.nest</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>-m</string>
        <string>owlia_nest</string>
        <string>serve</string>
        <string>--port</string><string>8788</string>
        <string>--prefix</string><string>/docs</string>
        <string>~/clawd/docs</string>
    </array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
</dict>
</plist>
EOF
launchctl load ~/Library/LaunchAgents/com.owlia.nest.plist
```

## CLI

```
owlia-nest [PATH...] [--port PORT] [--host HOST] [--prefix PREFIX]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--port` | `8788` | HTTP port |
| `--host` | `127.0.0.1` | Bind address |
| `--prefix` | `""` | URL prefix (e.g. `/docs`) |

Config saved to `~/.config/owlia-nest/dirs.json`

## Supported File Types

`.md` `.txt` `.py` `.ts` `.js` `.html` `.css` `.json` `.yaml` `.yml` `.toml` `.png` `.jpg` `.jpeg` `.gif` `.webp` `.svg` `.mp3` `.wav` `.ogg` `.m4a` `.opus`

## License

MIT
