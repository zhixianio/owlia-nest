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
- ✏️ Edit Markdown/text in the browser (EasyMDE, Ctrl+S to save); code files get a plain editor
- 🎨 5 themes + real syntax highlighting (Pygments, theme-aware)
- 📱 PWA — add to home screen on iOS/Android
- 🔍 Server-side search across all monitored dirs + category filters
- ⭐ Bookmark files **and folders**; folder bookmarks open in the browse tree
- 🚫 Exclude directories or file types from settings panel
- 🔐 Optional token auth for remote access (`--token`)
- 🔄 One-click upgrade from settings (checks GitHub tags)
- 🔗 Works with Caddy/nginx reverse proxy + Tailscale

## Remote Access

For remote access (your PA server is on another machine):

> ⚠️ If the server is reachable beyond localhost, set a token:
> `owlia-nest serve --token <secret>` (or add `"auth_token": "<secret>"` to the
> config). Then open `http://host:8788/docs/?token=<secret>` once per device —
> a year-long cookie keeps you logged in. Without a token, write APIs are
> reachable by anyone who can reach the port.

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
owlia-nest [PATH...] [--port PORT] [--host HOST] [--prefix PREFIX] [--token TOKEN]
```

Passing `PATH...` serves exactly those directories (config is ignored).
Without paths, directories come from the config — manage them with
`owlia-nest init / add / list`, or from the web settings panel.

| Flag | Default | Description |
|------|---------|-------------|
| `--port` | `8788` | HTTP port |
| `--host` | `127.0.0.1` | Bind address |
| `--prefix` | `""` | URL prefix (e.g. `/docs`) |
| `--token` | none | Require this access token (`?token=` once per device) |

Config saved to `~/.config/owlia-nest/dirs.json`. Extra keys: `auth_token`
(same as `--token`), `scan_depth` (home-page scan depth, default 4).

## Supported File Types

`.md` `.txt` `.py` `.ts` `.tsx` `.js` `.jsx` `.html` `.css` `.scss` `.sh` `.json` `.yaml` `.yml` `.toml` `.cfg` `.ini` `.png` `.jpg` `.jpeg` `.gif` `.webp` `.svg` `.mp3` `.wav` `.ogg` `.m4a` `.opus`

## Development

```bash
.venv/bin/python -m unittest discover tests   # run tests
.venv/bin/python tools/dev_serve.py           # dev server on :8788/docs
```

## License

MIT
