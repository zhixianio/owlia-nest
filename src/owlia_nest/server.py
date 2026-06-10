"""OWlia Docs server — Markdown renderer with themes, PWA, categorization, i18n."""

import base64
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse, quote
from html import escape

import markdown
from markdown.extensions import codehilite, fenced_code, tables, toc

MD_EXTENSIONS = [
    fenced_code.FencedCodeExtension(),
    codehilite.CodeHiliteExtension(guess_lang=False, css_class="highlight"),
    tables.TableExtension(),
    toc.TocExtension(permalink=False),
]

# ── Performance / caching ─────────────────────────────────────────
# Default directory depth for the home-page scan; override with the
# "scan_depth" key in the config file.
DEFAULT_SCAN_DEPTH = 4
# Shared cache for scanned files (populated by background scanner).
FILE_CACHE = {}

# ── Security ──────────────────────────────────────────────────────
_DANGEROUS_TAGS = r"script|style|iframe|object|embed|form|base|meta|link"

def _clean_tag(m):
    tag = m.group(0)
    tag = re.sub(r"(?i)\son\w+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", tag)
    tag = re.sub(r"(?i)(href|src)\s*=\s*(['\"]?)\s*javascript:[^'\">\s]*", r"\1=\2#", tag)
    return tag

def _sanitize_html(html: str) -> str:
    """Sanitize rendered markdown HTML (post-render, so escaped code samples
    in fences survive untouched): drop script/style with content, dangerous
    tags, inline on* handlers and javascript: URLs."""
    html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", html)
    html = re.sub(r"(?is)</?(%s)\b[^>]*>" % _DANGEROUS_TAGS, "", html)
    html = re.sub(r"<[^>]+>", _clean_tag, html)
    return html

# ── I18n ──────────────────────────────────────────────────────────
# Translation dictionary: Chinese key → {"zh": ..., "en": ...}
T = {
    # Brand / Header
    "Owlia Nest":           {"zh": "Owlia Nest", "en": "Owlia Nest"},
    "PA 产出文档中心":      {"zh": "PA 产出文档中心", "en": "PA Output Docs Hub"},

    # Categories
    "最近更新": {"zh": "最近更新", "en": "Recent"},
    "浏览":     {"zh": "浏览",     "en": "Browse"},
    "文档":     {"zh": "文档",     "en": "Docs"},
    "代码":     {"zh": "代码",     "en": "Code"},
    "配置":     {"zh": "配置",     "en": "Config"},
    "媒体":     {"zh": "媒体",     "en": "Media"},

    # Buttons & Actions
    "刷新":     {"zh": "刷新",     "en": "Refresh"},
    "管理目录": {"zh": "管理目录", "en": "Settings"},

    # Settings Panel
    "监控目录":                    {"zh": "监控目录",                    "en": "Monitored Dirs"},
    "输入目录路径，如 ~/my-project": {"zh": "输入目录路径，如 ~/my-project", "en": "Enter path, e.g. ~/my-project"},
    "+ 添加":                       {"zh": "+ 添加",                       "en": "+ Add"},
    "🚫 排除子目录":                 {"zh": "🚫 排除子目录",                 "en": "🚫 Exclude Subdirs"},
    "目录名，如 archive":            {"zh": "目录名，如 archive",            "en": "Dir name, e.g. archive"},
    "+ 排除":                       {"zh": "+ 排除",                       "en": "+ Exclude"},
    "🚫 排除文件类型":               {"zh": "🚫 排除文件类型",               "en": "🚫 Exclude Extensions"},
    "扩展名，如 .json":              {"zh": "扩展名，如 .json",              "en": "Extension, e.g. .json"},
    "下载":                        {"zh": "下载",                        "en": "Download"},
    "编辑":                        {"zh": "编辑",                        "en": "Edit"},
    "保存":                        {"zh": "保存",                        "en": "Save"},
    "取消":                        {"zh": "取消",                        "en": "Cancel"},
    "收藏":                        {"zh": "收藏",                        "en": "Bookmark"},
    "取消收藏":                    {"zh": "取消收藏",                    "en": "Unbookmark"},
    "已收藏":                      {"zh": "已收藏",                      "en": "Bookmarked"},

    # Navigation
    "← Home":     {"zh": "← Home",     "en": "← Home"},
    "← 返回首页": {"zh": "← 返回首页", "en": "← Back to Home"},

    # Content placeholders
    "暂无内容":     {"zh": "暂无内容",     "en": "No content yet"},
    "加载中…":     {"zh": "加载中…",     "en": "Loading…"},
    "暂无监控目录": {"zh": "暂无监控目录", "en": "No monitored dirs"},
    "无":           {"zh": "无",           "en": "None"},

    # File Card
    "排除此目录": {"zh": "排除此目录", "en": "Exclude Dir"},
    "排除类型":   {"zh": "排除类型",   "en": "Exclude Type"},

    # Time ago
    "刚才":   {"zh": "刚才",   "en": "just now"},
    "分钟前": {"zh": "分钟前", "en": "m ago"},
    "小时前": {"zh": "小时前", "en": "h ago"},
    "天前":   {"zh": "天前",   "en": "d ago"},

    # Media viewer
    "暂不支持预览此文件类型": {"zh": "暂不支持预览此文件类型", "en": "Preview not supported"},

    # Upgrade / Version
    "已发布（当前 v": {"zh": "已发布（当前 v", "en": "released (current v"},
    "）":             {"zh": "）",             "en": ")"},
    "⚡ 一键升级":    {"zh": "⚡ 一键升级",    "en": "⚡ Upgrade"},

    # ── JS-side strings (toast, alert, confirm, dynamic HTML) ──
    "🔄 新版本可用，点击更新":         {"zh": "🔄 新版本可用，点击更新",         "en": "🔄 New version available, tap to update"},
    "更新中…":                        {"zh": "更新中…",                        "en": "Updating…"},
    "⏳ 升级中…":                     {"zh": "⏳ 升级中…",                     "en": "⏳ Upgrading…"},
    "✅ 升级完成，等待服务重启…":     {"zh": "✅ 升级完成，等待服务重启…",     "en": "✅ Upgrade done, restarting…"},
    "点击刷新":                        {"zh": "点击刷新",                        "en": "Click to reload"},
    "✅ 服务已重启 ":                  {"zh": "✅ 服务已重启 ",                  "en": "✅ Restarted "},
    "❌ 升级失败: ":                   {"zh": "❌ 升级失败: ",                   "en": "❌ Upgrade failed: "},
    "未知错误":                        {"zh": "未知错误",                        "en": "unknown error"},
    "忽略":                            {"zh": "忽略",                            "en": "Dismiss"},
    "移除":                            {"zh": "移除",                            "en": "Remove"},
    "移除排除":                        {"zh": "移除排除",                        "en": "Remove exclusion"},
    "移除 ":                           {"zh": "移除 ",                           "en": "Remove "},
    " ？":                             {"zh": " ？",                             "en": "?"},
    "操作失败":                        {"zh": "操作失败",                        "en": "Operation failed"},
    "网络错误: ":                      {"zh": "网络错误: ",                      "en": "Network error: "},
    "将排除目录: ":                    {"zh": "将排除目录: ",                    "en": "Excluding dir: "},
    "\n（相同目录下的其他文件也会一并隐藏）": {"zh": "\n（相同目录下的其他文件也会一并隐藏）", "en": "\n(other files in the same dir will also be hidden)"},
    "✅ 已排除目录: ":                 {"zh": "✅ 已排除目录: ",                 "en": "✅ Excluded dir: "},
    "已恢复目录: ":                    {"zh": "已恢复目录: ",                    "en": "Restored dir: "},
    "将排除类型: ":                    {"zh": "将排除类型: ",                    "en": "Excluding type: "},
    "\n（所有同扩展名文件都会被隐藏）": {"zh": "\n（所有同扩展名文件都会被隐藏）", "en": "\n(all files with this extension will be hidden)"},
    "✅ 已排除类型: ":                 {"zh": "✅ 已排除类型: ",                 "en": "✅ Excluded type: "},
    "已恢复类型: ":                    {"zh": "已恢复类型: ",                    "en": "Restored type: "},
    "添加失败: ":                      {"zh": "添加失败: ",                      "en": "Add failed: "},
    "↩ 撤销":                         {"zh": "↩ 撤销",                         "en": "↩ Undo"},
}


def _(text, lang="zh"):
    """Look up translation for `text` in language `lang`. Falls back to `text`."""
    entry = T.get(text)
    if entry:
        return entry.get(lang, text)
    return text


def _lang_attr(lang):
    """Return HTML lang attribute value for the given language code."""
    return "zh-Hans" if lang == "zh" else "en"


def get_lang(handler):
    """Detect language from request: ?lang= query → cookie → Accept-Language → default 'zh'."""
    parsed = urlparse(handler.path)
    q = parse_qs(parsed.query)

    # 1. Query param
    lang = q.get("lang", [None])[0]
    if lang in ("zh", "en"):
        return lang

    # 2. Cookie
    cookie = handler.headers.get("Cookie", "")
    for part in cookie.split(";"):
        part = part.strip()
        if part.startswith("lang="):
            lang = part[5:].split(";")[0].strip()
            if lang in ("zh", "en"):
                return lang

    # 3. Accept-Language header
    al = handler.headers.get("Accept-Language", "")
    if "zh" in al:
        return "zh"
    if "en" in al:
        return "en"

    # 4. Default
    return "zh"


# ── Themes ────────────────────────────────────────────────────────
THEMES = {
    "github": {
        "name": "☀️ GitHub Light",
        "css": """\
  --bg: #ffffff; --fg: #1f2328; --accent: #0969da;
  --muted: #656d76; --border: #d0d7de; --card-bg: #f6f8fa; --code-bg: #f6f8fa;
  --tint: #ddf4ff;
  --syn-kw: #cf222e; --syn-str: #0a3069; --syn-com: #6e7781; --syn-num: #0550ae;
  --syn-fn: #8250df; --syn-cls: #953800; --syn-op: #24292f;""",
    },
    "github-dark": {
        "name": "🌙 GitHub Dark",
        "css": """\
  --bg: #0d1117; --fg: #e6edf3; --accent: #58a6ff;
  --muted: #8b949e; --border: #30363d; --card-bg: #161b22; --code-bg: #161b22;
  --tint: #0c2d6b;
  --syn-kw: #ff7b72; --syn-str: #a5d6ff; --syn-com: #8b949e; --syn-num: #79c0ff;
  --syn-fn: #d2a8ff; --syn-cls: #ffa657; --syn-op: #c9d1d9;""",
    },
    "nord": {
        "name": "❄️ Nord",
        "css": """\
  --bg: #2e3440; --fg: #d8dee9; --accent: #88c0d0;
  --muted: #81a1c1; --border: #4c566a; --card-bg: #3b4252; --code-bg: #3b4252;
  --tint: #434c5e;
  --syn-kw: #81a1c1; --syn-str: #a3be8c; --syn-com: #616e88; --syn-num: #b48ead;
  --syn-fn: #88c0d0; --syn-cls: #8fbcbb; --syn-op: #eceff4;""",
    },
    "dracula": {
        "name": "🧛 Dracula",
        "css": """\
  --bg: #282a36; --fg: #f8f8f2; --accent: #bd93f9;
  --muted: #6272a4; --border: #44475a; --card-bg: #343746; --code-bg: #343746;
  --tint: #44475a;
  --syn-kw: #ff79c6; --syn-str: #f1fa8c; --syn-com: #6272a4; --syn-num: #bd93f9;
  --syn-fn: #50fa7b; --syn-cls: #8be9fd; --syn-op: #f8f8f2;""",
    },
    "solarized": {
        "name": "📜 Solarized",
        "css": """\
  --bg: #fdf6e3; --fg: #657b83; --accent: #268bd2;
  --muted: #839496; --border: #93a1a1; --card-bg: #eee8d5; --code-bg: #eee8d5;
  --tint: #eee8d5;
  --syn-kw: #859900; --syn-str: #2aa198; --syn-com: #93a1a1; --syn-num: #d33682;
  --syn-fn: #268bd2; --syn-cls: #b58900; --syn-op: #657b83;""",
    },
}

def theme_dict(name):
    """Convert a theme's CSS string to a {var: value} dict for JS."""
    t = THEMES[name]
    out = {}
    for line in t["css"].strip().split(";"):
        line = line.strip()
        if line and ":" in line:
            k, v = line.split(":", 1)
            k = k.strip().lstrip("-")
            v = v.strip()
            if v:
                out[k] = v
    return out


def _ver_tuple(v):
    """Parse '1.2.3' → (1, 2, 3) for comparison; unparseable parts become 0."""
    parts = []
    for chunk in str(v).lstrip("v").split(".")[:4]:
        m = re.match(r"\d+", chunk)
        parts.append(int(m.group(0)) if m else 0)
    return tuple(parts + [0] * (4 - len(parts)))

LOCAL_VERSION = None
_VERSION_CHECKED_AT = 0
_VERSION_CACHE = None
_VERSION_TTL = 3600  # 1 hour

def _get_local_version():
    """Read version from installed package metadata."""
    global LOCAL_VERSION
    if LOCAL_VERSION:
        return LOCAL_VERSION
    try:
        from importlib.metadata import version
        LOCAL_VERSION = version("owlia-nest")
    except Exception:
        try:
            # Fallback: read from pyproject.toml next to this file
            pp = Path(__file__).resolve().parents[2] / "pyproject.toml"
            if pp.exists():
                import re
                text = pp.read_text()
                m = re.search(r'version\s*=\s*"([^"]+)"', text)
                if m:
                    LOCAL_VERSION = m.group(1)
        except Exception:
            LOCAL_VERSION = "0.0.0"
    return LOCAL_VERSION

def _check_remote_version():
    """Check GitHub for latest release tag. Cached for VERSION_TTL."""
    global _VERSION_CHECKED_AT, _VERSION_CACHE
    now = time.time()
    if _VERSION_CACHE and (now - _VERSION_CHECKED_AT) < _VERSION_TTL:
        return _VERSION_CACHE
    try:
        req = urllib.request.Request(
            "https://api.github.com/repos/zhixianio/owlia-nest/tags",
            headers={"Accept": "application/vnd.github+json", "User-Agent": "owlia-nest"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            latest = data[0]["name"].lstrip("v") if data else None
    except Exception:
        latest = None
    local = _get_local_version()
    _VERSION_CACHE = {
        "local": local,
        "latest": latest or local,
        "has_update": latest is not None and _ver_tuple(latest) > _ver_tuple(local),
    }
    _VERSION_CHECKED_AT = now
    return _VERSION_CACHE

def _manifest(prefix=""):
    return json.dumps({
        "name": "Owlia Nest",
        "short_name": "Owlia Nest",
        "start_url": f"{prefix}/",
        "scope": f"{prefix}/",
        "display": "standalone",
        "background_color": "#0d1117",
        "theme_color": "#0969da",
        "icons": [
            {"src": f"{prefix}/icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": f"{prefix}/icons/icon-512.png", "sizes": "512x512", "type": "image/png"},
        ],
    }, indent=2)

def _load_icon(name):
    p = Path(__file__).resolve().parent / "icons" / name
    return p.read_bytes() if p.exists() else None

ICONS = {}  # path -> (mime, bytes)
ICON_NAMES = ["favicon-32.png", "icon-192.png", "icon-512.png", "logo.png"]
for name in ICON_NAMES:
    data = _load_icon(name)
    if data:
        ICONS[name] = ("image/png", data)

def _sw_js(prefix=""):
    return f"""const CACHE = 'owlia-nest-v5-{prefix}';
const ICON_RE = /\\/(icons|favicon)\\.(png|ico)/;

self.addEventListener('install', e => {{
  self.skipWaiting();
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll([
      '{prefix}/',
      '{prefix}/icons/logo.png',
      '{prefix}/icons/icon-192.png',
      '{prefix}/icons/icon-512.png',
    ]).catch(() => {{}}))
  );
}});

self.addEventListener('activate', e => {{
  e.waitUntil(
    caches.keys().then(keys => Promise.all(
      keys.filter(k => k !== CACHE).map(k => caches.delete(k))
    ))
  );
  clients.claim();
}});

self.addEventListener('fetch', e => {{
  const url = new URL(e.request.url);
  // Cache-first for icons
  if (ICON_RE.test(url.pathname)) {{
    e.respondWith(
      caches.match(e.request).then(r => r || fetch(e.request).then(resp => {{
        if (resp.ok) {{ caches.open(CACHE).then(c => c.put(e.request, resp.clone())); }}
        return resp;
      }}))
    );
    return;
  }}
  // Never cache API or non-GET requests
  if (url.pathname.includes('/api/') || e.request.method !== 'GET') {{
    return;
  }}
  // Network-first for content
  e.respondWith(
    fetch(e.request).then(resp => {{
      if (resp.ok) {{ caches.open(CACHE).then(c => c.put(e.request, resp.clone())); }}
      return resp;
    }}).catch(() => caches.match(e.request))
  );
}});

self.addEventListener('message', e => {{
  if (e.data === 'skip-waiting') self.skipWaiting();
}});
"""

# CSS lives in static/app.css; page JS in static/app.js (config via window.OWLIA).
PAGE_TPL = """\
<!doctype html>
<html lang="{lang_attr}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{title}</title>
<link rel="icon" type="image/png" sizes="32x32" href="{api_base}/icons/favicon-32.png">
<link rel="apple-touch-icon" sizes="192x192" href="{api_base}/icons/icon-192.png">
<link rel="shortcut icon" href="{api_base}/favicon.ico">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Owlia Nest">
<meta name="theme-color" content="#0d1117">
<link rel="stylesheet" href="{api_base}/static/app.css">
<style>
:root {{ {__theme_css__} }}
</style>
<script>window.OWLIA = {__owlia_cfg__};</script>
{head_extra}
</head>
<body>
<div class="container">
{body}
</div>
<script src="{api_base}/static/app.js"></script>
</body>
</html>
"""

CATEGORIES = {
    "recent": ("🕐", "最近更新"), "doc": ("📄", "文档"),
    "code": ("💻", "代码"), "config": ("⚙️", "配置"), "media": ("🎬", "媒体"),
    "fav": ("⭐", "收藏"),
    "browse": ("📁", "浏览"),
}
# ── Extension registry: ext → (category, icon, mime) ─────────────
# Single source of truth for what we scan, how we classify/iconify it,
# and what MIME we serve it with.
EXTENSIONS = {
    "md":   ("doc", "📄", "text/markdown"),
    "txt":  ("doc", "📝", "text/plain"),
    "py":   ("code", "🐍", "text/x-python"),
    "ts":   ("code", "🔷", "text/plain"),
    "tsx":  ("code", "🔷", "text/plain"),
    "js":   ("code", "📜", "application/javascript"),
    "jsx":  ("code", "📜", "text/plain"),
    "html": ("code", "🌐", "text/html"),
    "css":  ("code", "🎨", "text/css"),
    "scss": ("code", "🎨", "text/plain"),
    "sh":   ("code", "📜", "text/x-shellscript"),
    "json": ("config", "⚙️", "application/json"),
    "yaml": ("config", "⚙️", "text/plain"),
    "yml":  ("config", "⚙️", "text/plain"),
    "toml": ("config", "⚙️", "text/plain"),
    "cfg":  ("config", "⚙️", "text/plain"),
    "ini":  ("config", "⚙️", "text/plain"),
    "png":  ("media", "🖼️", "image/png"),
    "jpg":  ("media", "🖼️", "image/jpeg"),
    "jpeg": ("media", "🖼️", "image/jpeg"),
    "gif":  ("media", "🖼️", "image/gif"),
    "webp": ("media", "🖼️", "image/webp"),
    "svg":  ("media", "🖼️", "image/svg+xml"),
    "mp3":  ("media", "🎵", "audio/mpeg"),
    "wav":  ("media", "🎵", "audio/wav"),
    "ogg":  ("media", "🎵", "audio/ogg"),
    "m4a":  ("media", "🎵", "audio/mp4"),
    "opus": ("media", "🎵", "audio/opus"),
}
VALID_EXTS = {"." + e for e in EXTENSIONS}
MEDIA_EXTS = {"." + e for e, v in EXTENSIONS.items() if v[0] == "media"}

def _ext_of(name):
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""

def mime_for(name, default="application/octet-stream"):
    entry = EXTENSIONS.get(_ext_of(name))
    return entry[2] if entry else default

# ── File scanning ─────────────────────────────────────────────────
# Default dirs are relative to workspace, detected at init time.
# Fallback list used only if no config exists.
DEFAULT_DIRS = [
    "~/clawd/docs",  # legacy
    "~/clawd/memory",
    "~/clawd",
    "~/.openclaw/workspace/docs",
    "~/.openclaw/workspace/memory",
    "~/.openclaw/workspace",
]

def _expand(p):
    return Path(p).expanduser().resolve()

# Serializes all read-modify-write cycles on the config file. RLock so
# helpers can nest (e.g. a handler holding the lock calls load+save).
_CONFIG_LOCK = threading.RLock()

def _config_file(config_path=None):
    if config_path is None:
        config_path = Path.home() / ".config" / "owlia-nest" / "dirs.json"
    return _expand(config_path)

def _read_config_raw(config_path=None):
    path = _config_file(config_path)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {}

def _write_config_raw(data, config_path=None):
    path = _config_file(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))
    return path

def load_config(config_path=None):
    with _CONFIG_LOCK:
        path = _config_file(config_path)
        if path.exists():
            data = _read_config_raw(config_path)
            dirs = [_expand(p) for p in data.get("dirs", [])]
            return dirs, data.get("exclude_dirs", []), data.get("exclude_exts", [])
    # fallback: scan default dirs if they exist
    dirs = [_expand(d) for d in DEFAULT_DIRS if _expand(d).exists()]
    return dirs, [], []

def save_config(dirs, config_path=None, exclude_dirs=None, exclude_exts=None):
    with _CONFIG_LOCK:
        # Start from existing data so unrelated keys (favorites, …) survive.
        data = _read_config_raw(config_path)
        data["dirs"] = [str(d) for d in dirs]
        if exclude_dirs is not None:
            data["exclude_dirs"] = exclude_dirs
        else:
            data.setdefault("exclude_dirs", [])
        if exclude_exts is not None:
            data["exclude_exts"] = exclude_exts
        else:
            data.setdefault("exclude_exts", [])
        return _write_config_raw(data, config_path)

def load_favorites(config_path=None):
    """Load favorited paths (files or dirs) from config."""
    with _CONFIG_LOCK:
        return set(_read_config_raw(config_path).get("favorites", []))

def save_favorites(favorites, config_path=None):
    """Save favorited paths to config."""
    with _CONFIG_LOCK:
        data = _read_config_raw(config_path)
        data["favorites"] = sorted(favorites)
        return _write_config_raw(data, config_path)

def toggle_favorite(fpath, config_path=None):
    """Atomically toggle a favorite. Returns (action, favorites)."""
    with _CONFIG_LOCK:
        favs = load_favorites(config_path)
        if fpath in favs:
            favs.discard(fpath)
            action = "removed"
        else:
            favs.add(fpath)
            action = "added"
        save_favorites(favs, config_path)
        return action, favs

def scan_file(path, root):
    stat = path.stat()
    return {
        "name": path.name, "path": str(path),
        "mtime": stat.st_mtime,
        "mtime_str": time.strftime("%m-%d %H:%M", time.localtime(stat.st_mtime)),
        "size": stat.st_size, "is_dir": path.is_dir(),
        "rel_path": str(path.relative_to(root)), "root": str(root),
    }

def _iter_files_scandir(root: Path, max_depth: int, skip_parts, skip_paths, exclude_ext_set, valid_ext):
    stack = [(root, 0)]
    while stack:
        cur, depth = stack.pop()
        try:
            with os.scandir(cur) as it:
                for entry in it:
                    name = entry.name
                    if name.startswith("."):
                        continue
                    try:
                        p = Path(entry.path)
                    except Exception:
                        continue
                    if skip_parts and (skip_parts & set(p.parts)):
                        continue
                    if skip_paths and any(skip_path in p.parents for skip_path in skip_paths):
                        continue
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if depth < max_depth:
                                stack.append((p, depth + 1))
                        elif entry.is_file(follow_symlinks=False):
                            ext = p.suffix.lower()
                            if ext in exclude_ext_set:
                                continue
                            if ext in valid_ext:
                                yield p
                    except OSError:
                        continue
        except OSError:
            continue

def scan_files(targets, exclude_dirs=None, exclude_exts=None, max_depth=None):
    if max_depth is None:
        max_depth = DEFAULT_SCAN_DEPTH
    files = []
    skip_parts = {"__pycache__", "node_modules", ".git"}
    skip_paths = []  # full paths to exclude
    if exclude_dirs:
        for d in exclude_dirs:
            dp = Path(d)
            if dp.is_absolute() or "/" in d:
                skip_paths.append(dp)
            else:
                skip_parts.add(d)
    exclude_ext_set = set(exclude_exts) if exclude_exts else set()
    valid_ext = VALID_EXTS
    for target in targets:
        if not target.exists():
            continue
        if target.is_file():
            info = scan_file(target, target.parent)
            info["rel_path"] = target.name
            files.append(info)
        elif target.is_dir():
            for fpath in _iter_files_scandir(
                target,
                max_depth,
                skip_parts,
                skip_paths,
                exclude_ext_set,
                valid_ext,
            ):
                try:
                    files.append(scan_file(fpath, target))
                except OSError:
                    continue
    # Deduplicate by absolute path: keep entry from most specific (closest) root
    seen = {}
    for f in files:
        apath = f["path"]
        if apath not in seen or len(f["rel_path"]) < len(seen[apath]["rel_path"]):
            seen[apath] = f
    files = list(seen.values())
    files.sort(key=lambda f: f["mtime"], reverse=True)
    return files

def browse_dir(path: Path, cap: int = 5000):
    dirs = []
    files = []
    count = 0
    try:
        with os.scandir(path) as it:
            for entry in it:
                if count >= cap:
                    break
                name = entry.name
                if name.startswith("."):
                    continue
                p = Path(entry.path)
                try:
                    if entry.is_dir(follow_symlinks=False):
                        dirs.append({"name": name, "path": str(p)})
                    elif entry.is_file(follow_symlinks=False):
                        st = entry.stat(follow_symlinks=False)
                        files.append({"name": name, "path": str(p), "mtime": st.st_mtime, "size": st.st_size})
                    count += 1
                except OSError:
                    continue
    except OSError:
        return {"ok": False, "error": "not readable", "dirs": [], "files": [], "truncated": False}
    dirs.sort(key=lambda d: d["name"].lower())
    files.sort(key=lambda f: f["name"].lower())
    return {"ok": True, "dirs": dirs, "files": files, "truncated": count >= cap}

# ── Utilities ─────────────────────────────────────────────────────
def size_fmt(n):
    if n < 1024: return f"{n}B"
    if n < 1024 * 1024: return f"{n / 1024:.0f}KB"
    return f"{n / (1024*1024):.0f}MB"

def time_ago(mtime, lang="zh"):
    diff = time.time() - mtime
    if diff < 60:
        return _("刚才", lang)
    if diff < 3600:
        return f"{int(diff / 60)}{_('分钟前', lang)}"
    if diff < 86400:
        return f"{int(diff / 3600)}{_('小时前', lang)}"
    if diff < 604800:
        return f"{int(diff / 86400)}{_('天前', lang)}"
    return time.strftime("%m-%d %H:%M", time.localtime(mtime))

def classify(f):
    entry = EXTENSIONS.get(_ext_of(f["name"]))
    return entry[0] if entry else "other"

def icon_for(f):
    entry = EXTENSIONS.get(_ext_of(f["name"]))
    if entry:
        return entry[1]
    return "📁" if f.get("is_dir") else "📎"

def fr_query(f_rel, root):
    """URL-encoded `f=<rel>&r=<root>` query string for view/media/download links."""
    return f"f={quote(str(f_rel))}&r={quote(str(root))}"

# ── HTML builders ─────────────────────────────────────────────────
def mk_page(title, body, head_extra="", default_theme="github-dark", prefix="", lang="zh"):
    cfg = json.dumps({
        "prefix": prefix,
        "lang": lang,
        "i18n": {k: v.get(lang, k) for k, v in T.items()},
        "themes": {k: theme_dict(k) for k in THEMES},
        "defaultTheme": default_theme,
    }, ensure_ascii=False).replace("</", "<\\/")
    return PAGE_TPL.format(
        title=title, body=body, head_extra=head_extra or "",
        __theme_css__=THEMES[default_theme]["css"].strip(),
        __owlia_cfg__=cfg,
        api_base=prefix, lang_attr=_lang_attr(lang),
    )

def file_card(f, href, lang="zh"):
    dname = os.path.dirname(f["path"])
    fpath = f["path"]
    ext = _ext_of(f["name"])
    safe_name = escape(f["name"])
    safe_fpath = escape(fpath)
    return (
        f'<div class="file-card" data-cat="{classify(f)}">'
        f'<span class="file-icon">{icon_for(f)}</span>'
        f'<button class="btn-star" data-filepath="{escape(fpath)}" title="{_("收藏", lang)}" onclick="event.preventDefault();event.stopPropagation();toggleFav(this.dataset.filepath,this)">☆</button>'
        f'<span class="file-name"><a href="{href}?{fr_query(f["rel_path"], f["root"])}" data-filepath="{escape(fpath)}">{safe_name}</a>'
        f'<br><span class="file-path">{safe_fpath}</span></span>'
        f'<span class="file-date">{time_ago(f["mtime"], lang)}</span>'
        f'<span class="file-size">{size_fmt(f["size"])}</span>'
        f'<span class="file-actions">'
        f'<button class="btn-tiny" data-exclude-dir="{escape(dname)}" title="{_("排除此目录", lang)}">{_("排除此目录", lang)}</button>'
        + (f'<button class="btn-tiny" data-exclude-ext=".{ext}" title="{_("排除类型", lang)} .{ext}">{_("排除类型", lang)}</button>' if ext else '') +
        f'</span></div>'
    )

def render_home(files, prefix="", lang="zh"):
    view_url = prefix + "/view"
    cats = {k: [] for k in CATEGORIES}
    cats["recent"] = [file_card(f, view_url, lang) for f in files[:30]]
    for f in files:
        c = classify(f)
        if c in cats:
            cats[c].append(file_card(f, view_url, lang))

    tabs = '<nav class="tabs-bar" aria-label="Categories">'
    for key, (emoji, label) in CATEGORIES.items():
        active = ' class="tab-active"' if key == "recent" else ""
        cnt = len(cats[key])
        cnt_str = f' <span class="tab-count">{cnt}</span>' if cnt else ""
        tabs += f'<button{active} data-tab="{key}">{emoji} {_(label, lang)}{cnt_str}</button>'
    tabs += '</nav>'

    secs = []
    for key, cards in cats.items():
        hidden = '' if key == "recent" else ' style="display:none"'
        if key == "browse":
            secs.append(
                f'<section class="tab-panel" data-panel="{key}"{hidden}>'
                f'<div id="browseBreadcrumbs" class="breadcrumb" style="margin-bottom:0.75rem"></div>'
                f'<div id="browseList"></div>'
                f'</section>'
            )
        elif key == "fav":
            secs.append(
                f'<section class="tab-panel" data-panel="{key}"{hidden}>'
                f'<p style="color:var(--muted);padding:2rem;text-align:center">{_("加载中…", lang)}</p>'
                f'</section>'
            )
        elif cards:
            secs.append(f'<section class="tab-panel" data-panel="{key}"{hidden}>{"".join(cards)}</section>')
        else:
            secs.append(f'<section class="tab-panel" data-panel="{key}"{hidden}><p style="color:var(--muted);padding:2rem;text-align:center">{_("暂无内容", lang)}</p></section>')

    theme_opts = "".join(f'<option value="{k}">{v["name"]}</option>' for k, v in THEMES.items())
    ver = _check_remote_version()
    local_ver = ver["local"]
    has_update = ver.get("has_update")
    latest_ver = ver.get("latest", "")
    version_html = f'<span class="version-tag">v{local_ver}</span>'
    upgrade_banner = ""
    if has_update and latest_ver:
        version_html += f' <span class="version-upgrade" onclick="upgradeNow()">🆕 v{latest_ver}</span>'
        upgrade_banner = (
            f'<div id="upgradeBanner" class="upgrade-banner">'
            f'🆕 <strong>v{latest_ver}</strong> {_("已发布（当前 v", lang)}{local_ver}{_("）", lang)}'
            f'<br><button onclick="upgradeNow()" class="btn-add" style="margin:0.25rem 0">{_("⚡ 一键升级", lang)}</button>'
            f'<br><small id="upgradeStatus" style="color:var(--muted)"></small>'
            f'</div>'
        )
    header = f"""<header>
  <div class="header-brand"><img src="{prefix}/icons/logo.png" alt="Owlia Nest" class="logo" width="32" height="32"><div><h1>Owlia Nest</h1><p>{_("PA 产出文档中心", lang)}</p></div></div>
  <div class="header-right">
    <button class="lang-toggle" onclick="toggleLang()" title="中 | EN">{_("中 | EN", lang)}</button>
    {version_html}
    <button class="theme-select" id="settingsToggle" title="{_("管理目录", lang)}" onclick="toggleSettings()">⚙️</button>
    <select class="theme-select" id="themeSelect">{theme_opts}</select>
    <button class="theme-select" onclick="location.reload()" title="{_("刷新", lang)}">↻</button>
  </div>
</header>
{upgrade_banner}
<div class="search-row" style="margin:0.75rem 0 1rem">
  <input id="searchInput" type="search" placeholder="Search..." oninput="doSearch()" style="width:100%;padding:0.6rem 0.75rem;border-radius:10px;border:1px solid var(--border);background:var(--card-bg);color:var(--fg);outline:none">
</div>
<div id="settingsPanel" class="settings-panel" style="display:none">
  <div class="settings-title">📂 {_("监控目录", lang)}</div>
  <div id="dirList" class="dir-list">{_("加载中…", lang)}</div>
  <div class="add-dir-row">
    <input id="dirInput" type="text" class="dir-input" placeholder="{_("输入目录路径，如 ~/my-project", lang)}">
    <button class="btn-add" onclick="addDir()">{_("+ 添加", lang)}</button>
  </div>
  <div class="settings-title" style="margin-top:1rem">{_("🚫 排除子目录", lang)}</div>
  <div id="excludeDirList" class="exclude-list">{_("加载中…", lang)}</div>
  <div class="add-dir-row">
    <input id="excludeDirInput" type="text" class="dir-input" placeholder="{_("目录名，如 archive", lang)}">
    <button class="btn-add" onclick="addExcludeDir()">{_("+ 排除", lang)}</button>
  </div>
  <div class="settings-title" style="margin-top:1rem">{_("🚫 排除文件类型", lang)}</div>
  <div id="excludeExtList" class="exclude-list">{_("加载中…", lang)}</div>
  <div class="add-dir-row">
    <input id="excludeExtInput" type="text" class="dir-input" placeholder="{_("扩展名，如 .json", lang)}">
    <button class="btn-add" onclick="addExcludeExt()">{_("+ 排除", lang)}</button>
  </div>
</div>"""

    head_extra = f'<link rel="manifest" href="{prefix}/manifest.json">'
    search_panel = '<section id="searchResults" class="tab-panel" style="display:none"></section>'
    body = header + tabs + search_panel + "\n".join(secs)
    return mk_page("Owlia Nest", body, head_extra, prefix=prefix, lang=lang)

def _file_breadcrumb(path, prefix, f_rel, f_root, lang="zh"):
    """Build breadcrumb HTML for file view pages with clickable directory path."""
    rel = f_rel or path.name
    parts = Path(rel).parts
    f_root_str = str(f_root) if f_root else str(path.parent)
    crumbs = [f'<a href="{prefix}/">{_("← Home", lang)}</a>']
    cur_parts = []
    for part in parts:
        cur_parts.append(part)
        if part == parts[-1]:
            # Last part is the file itself — plain text
            crumbs.append(escape(part))
        else:
            # Directory — link to home page with ?browse=<dirPath> to auto-navigate
            dir_rel = "/".join(cur_parts)
            dir_abs = str(Path(f_root_str) / dir_rel)
            safe_dir = quote(dir_abs, safe='')
            crumbs.append(
                '<a href="' + prefix + '/?browse=' + safe_dir + '">' +
                escape(part) + '</a>'
            )
    return " / ".join(crumbs)


def _json_for_script(obj):
    """JSON safe to embed inside a <script> block (escapes </script>)."""
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


def render_doc(path, prefix="", lang="zh", f_rel=None, f_root=None, mode="txt"):
    """Render a text-like file view with editor. mode: md | txt | plain."""
    raw = path.read_text(encoding="utf-8", errors="replace")
    if mode == "md":
        html = _sanitize_html(markdown.markdown(raw, extensions=MD_EXTENSIONS))
        view_html = f'<div id="mdView" class="markdown-body">{html}</div>'
    elif mode == "plain":
        try:
            from pygments import highlight as _pyg_highlight
            from pygments.lexers import get_lexer_for_filename
            from pygments.formatters import HtmlFormatter
            lexer = get_lexer_for_filename(path.name, raw)
            code_html = _pyg_highlight(raw, lexer, HtmlFormatter(cssclass="highlight"))
        except Exception:
            code_html = f'<pre>{escape(raw)}</pre>'
        view_html = (f'<div id="mdView" class="markdown-body" '
                     f'style="font-size:0.875rem">{code_html}</div>')
    else:
        view_html = (f'<div id="mdView"><pre style="background:var(--code-bg);padding:1rem;'
                     f'border-radius:8px;overflow-x:auto;white-space:pre-wrap;font-size:0.875rem;'
                     f'border:1px solid var(--border)">{escape(raw)}</pre></div>')

    f_rel = str(f_rel or path.name)
    f_root = str(f_root or path.parent)
    dl_url = f"{prefix}/download?{fr_query(f_rel, f_root)}"
    theme_opts = "".join(f'<option value="{k}">{v["name"]}</option>' for k, v in THEMES.items())
    safe_name = escape(path.name)
    editor_cfg = _json_for_script({
        "f": f_rel, "r": f_root, "prefix": prefix, "mode": mode,
        "saveLabel": _("保存", lang),
    })
    easymde_tag = "" if mode == "plain" else f'<script src="{prefix}/static/easymde.js"></script>'
    head_extra = (
        f'<link rel="stylesheet" href="{prefix}/static/editor.css">'
        f'{easymde_tag}'
        f'<script type="application/json" id="owliaEditorCfg">{editor_cfg}</script>'
        f'<script type="application/json" id="mdRawData">{_json_for_script(raw)}</script>'
        f'<script defer src="{prefix}/static/editor.js"></script>'
    )
    breadcrumb = _file_breadcrumb(path, prefix, f_rel, f_root, lang)
    body = f"""<header><div class="header-brand"><img src="{prefix}/icons/logo.png" alt="Owlia Nest" class="logo" width="32" height="32"><h1>Owlia Nest</h1></div>
  <div class="header-right">
    <button class="lang-toggle" onclick="toggleLang()" title="中 | EN">{_("中 | EN", lang)}</button>
    <select class="theme-select" id="themeSelect">{theme_opts}</select></div></header>
<div class="breadcrumb">{breadcrumb} <a href="{dl_url}" class="btn-dl" title="{_('下载', lang)}">⬇</a> <button id="btnEdit" class="btn-edit" title="{_('编辑', lang)}" onclick="toggleEdit()">✏️ {_('编辑', lang)}</button><button id="btnSave" class="btn-edit" title="{_('保存', lang)}" onclick="saveEdit()" style="display:none">💾 {_('保存', lang)}</button><button id="btnCancel" class="btn-edit" title="{_('取消', lang)}" onclick="cancelEdit()" style="display:none">❌ {_('取消', lang)}</button></div>
{view_html}
<div id="mdEditor" style="display:none"><textarea id="mdTextarea"></textarea></div>
<div class="back-link"><a href="{prefix}/">{_("← 返回首页", lang)}</a></div>"""
    return mk_page(f"{safe_name} — Owlia Nest", body, head_extra, prefix=prefix, lang=lang)

def render_media(path, prefix="", lang="zh"):
    """Render image/audio files with inline embed."""
    ext = path.suffix.lower()
    dl_url = f"{prefix}/download?{fr_query(path.name, path.parent)}"
    theme_opts = "".join(f'<option value="{k}">{v["name"]}</option>' for k, v in THEMES.items())
    media_url = f"{prefix}/media?{fr_query(path.name, path.parent)}"
    safe_name = escape(path.name)

    mime = mime_for(path.name)
    if mime.startswith("image/"):
        elem = f'<img src="{media_url}" alt="{safe_name}" style="max-width:100%;height:auto;border-radius:6px;display:block">'
    elif mime.startswith("audio/"):
        elem = f'<audio controls preload="auto" style="width:100%;max-width:480px"><source src="{media_url}" type="{mime}"></audio>'
    else:
        elem = f'<p style="color:var(--muted)">{_("暂不支持预览此文件类型", lang)}</p>'

    body = f"""<header><div class="header-brand"><img src="{prefix}/icons/logo.png" alt="Owlia Nest" class="logo" width="32" height="32"><h1>Owlia Nest</h1></div>
  <div class="header-right">
    <button class="lang-toggle" onclick="toggleLang()" title="中 | EN">{_("中 | EN", lang)}</button>
    <select class="theme-select" id="themeSelect">{theme_opts}</select></div></header>
<div class="breadcrumb">{_file_breadcrumb(path, prefix, None, path.parent, lang)} <a href="{dl_url}" class="btn-dl" title="{_('下载', lang)}">⬇</a></div>
<div style="margin:1rem 0">{elem}</div>
<div style="margin-top:0.5rem;color:var(--muted);font-size:0.8rem">{safe_name} · {size_fmt(path.stat().st_size)}</div>
<div class="back-link"><a href="{prefix}/">{_("← 返回首页", lang)}</a></div>"""
    return mk_page(f"{safe_name} — Owlia Nest", body, prefix=prefix, lang=lang)

# ── WSGI/HTTP handler ────────────────────────────────────────────
def create_app(targets=None, prefix="", ephemeral=False, auth_token=None, config_path=None):
    """Build the request handler.

    ephemeral=True means targets were given explicitly (CLI args): never
    reload/overwrite them from the on-disk config.
    auth_token, when set, requires every request to carry a matching
    `owlia_auth` cookie or one-time `?token=` query (which sets the cookie).
    """
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    def _path_is_within(path: Path, parent: Path) -> bool:
        try:
            path.resolve().relative_to(parent.resolve())
            return True
        except Exception:
            return False

    if targets is None:
        targets, exclude_dirs, exclude_exts = load_config()
    else:
        # targets passed directly (from serve arg or loaded elsewhere)
        if isinstance(targets, tuple) and len(targets) == 3:
            targets, exclude_dirs, exclude_exts = targets
        else:
            exclude_dirs, exclude_exts = [], []
    # Normalize: handlers compare resolved request paths against these, so
    # an unresolved symlinked target (/var vs /private/var on macOS) would
    # pass the containment check but blow up relative_to() later.
    targets = [Path(t).expanduser().resolve() for t in targets]
    # Wrap in list to allow mutation from nested Handler
    _state = [targets, exclude_dirs, exclude_exts]
    if config_path is None:
        config_path = Path.home() / ".config" / "owlia-nest" / "dirs.json"
    prefix = prefix.rstrip("/")

    _cache = FILE_CACHE
    if "files" not in _cache:
        _cache["files"] = []
    if "scanning" not in _cache:
        _cache["scanning"] = False
    if "last_scan" not in _cache:
        _cache["last_scan"] = 0.0
    if "error" not in _cache:
        _cache["error"] = None

    _cache_lock = threading.Lock()
    _state_lock = threading.Lock()

    def _start_scan_async(force=False):
        with _cache_lock:
            if _cache.get("scanning") and not force:
                return
            _cache["scanning"] = True
            _cache["error"] = None

        def _worker():
            try:
                with _state_lock:
                    _t, _e, _x = _state[0], _state[1], _state[2]
                    _t = list(_t)
                    _e = list(_e)
                    _x = list(_x)
                try:
                    depth = int(_read_config_raw().get("scan_depth", DEFAULT_SCAN_DEPTH))
                except (TypeError, ValueError):
                    depth = DEFAULT_SCAN_DEPTH
                files = scan_files(_t, _e, _x, max_depth=depth)
                with _cache_lock:
                    _cache["files"] = files
                    _cache["last_scan"] = time.time()
                    _cache["error"] = None
            except Exception as e:
                with _cache_lock:
                    _cache["error"] = str(e)
            finally:
                with _cache_lock:
                    _cache["scanning"] = False

        th = threading.Thread(target=_worker, name="owlia-nest-scan", daemon=True)
        th.start()

    def _check_post_origin(headers) -> bool:
        origin = (headers.get("Origin") or "").strip()
        # Allow requests without Origin (e.g., PWA, direct fetch, curl)
        if not origin:
            return True
        allow = ("http://localhost", "http://127.0.0.1", "http://0.0.0.0",
                 "https://localhost", "https://127.0.0.1", "https://0.0.0.0",
                 "capacitor://localhost", "file://")
        if origin.startswith(allow):
            return True
        # Same-origin: the Origin host must match the Host the request came
        # to (covers Tailscale IPs and reverse-proxy domains). A foreign
        # Origin (cross-site CSRF) never matches and is rejected.
        host = (headers.get("Host") or "").strip()
        try:
            o_netloc = urlparse(origin).netloc
            if o_netloc and host and o_netloc.lower() == host.lower():
                return True
        except Exception:
            pass
        return False

    class Handler(BaseHTTPRequestHandler):
        def _authed(self):
            if not auth_token:
                return True
            for part in (self.headers.get("Cookie") or "").split(";"):
                part = part.strip()
                if part.startswith("owlia_auth=") and part[len("owlia_auth="):] == auth_token:
                    return True
            q = parse_qs(urlparse(self.path).query)
            if q.get("token", [None])[0] == auth_token:
                self._set_auth_cookie = True  # picked up by _send
                return True
            return False

        def do_GET(self):
            parsed = urlparse(self.path)
            raw_path = parsed.path
            path = raw_path[len(prefix):] if prefix and raw_path.startswith(prefix) else raw_path
            if not path.startswith("/"):
                path = "/" + path
            # PWA assets stay public: browsers fetch the manifest (and its
            # icons) without credentials, so gating them breaks installs.
            public = (path == "/manifest.json" or path == "/favicon.ico"
                      or path.startswith("/icons/"))
            if not public and not self._authed():
                self.send_error(401, "Unauthorized (append ?token=<token> once to log in)")
                return
            q = parse_qs(parsed.query)
            targets, exclude_dirs, exclude_exts = _state
            lang = get_lang(self)

            if path == "/sw.js":
                self._send(_sw_js(prefix), "application/javascript; charset=utf-8")
            elif path.startswith("/static/"):
                self._static(Path(__file__).resolve().parent / "static", path[len("/static/"):])
            elif path.startswith("/icons/") and path[7:] in ICONS:
                mime, data = ICONS[path[7:]]
                self._send(data, mime)
            elif path.startswith("/icons/"):
                self._static(Path(__file__).resolve().parent / "icons", path[len("/icons/"):])
            elif path == "/favicon.ico":
                if "favicon-32.png" in ICONS:
                    mime, data = ICONS["favicon-32.png"]
                    self._send(data, mime)
                else:
                    self.send_error(404)
            elif path == "/manifest.json":
                self._send(_manifest(prefix), "application/json; charset=utf-8")
            elif path == "/api/dirs":
                # Reload from disk to catch external changes
                if ephemeral:
                    _t, _e, _x = targets, exclude_dirs, exclude_exts
                else:
                    _t, _e, _x = load_config(config_path)
                _favs = load_favorites(config_path)
                self._send(json.dumps({
                    "dirs": [str(d) for d in _t],
                    "exclude_dirs": _e,
                    "exclude_exts": _x,
                    "favorites": sorted(_favs),
                }), "application/json; charset=utf-8")
            elif path == "/api/version":
                info = _check_remote_version()
                self._send(json.dumps(info), "application/json; charset=utf-8")
            elif path == "/api/favorites":
                # Rich entries: favorites can be files OR directories.
                favs = load_favorites(config_path)
                entries = []
                for fp in sorted(favs):
                    p = Path(fp)
                    exists = p.exists()
                    is_dir = exists and p.is_dir()
                    entry = {"path": fp, "name": p.name or fp,
                             "exists": exists, "is_dir": is_dir}
                    if exists:
                        try:
                            entry["mtime_ago"] = time_ago(p.stat().st_mtime, lang)
                        except OSError:
                            pass
                        if not is_dir:
                            entry["icon"] = icon_for({"name": p.name})
                            for t in targets:
                                if _path_is_within(p, t):
                                    rel = p.resolve().relative_to(t.resolve())
                                    entry["view_url"] = f"{prefix}/view?{fr_query(rel, t)}"
                                    break
                    entries.append(entry)
                self._send(json.dumps({"favorites": entries}, ensure_ascii=False),
                           "application/json; charset=utf-8")
            elif path == "/api/cache-status":
                with _cache_lock:
                    payload = {
                        "scanning": bool(_cache.get("scanning")),
                        "last_scan": _cache.get("last_scan") or 0,
                        "count": len(_cache.get("files") or []),
                        "error": _cache.get("error"),
                    }
                self._send(json.dumps(payload), "application/json; charset=utf-8")
            elif path == "/api/search":
                qstr = (q.get("q", [""])[0] or "").strip().lower()
                terms = qstr.split()
                if not terms:
                    self._send(json.dumps({"ok": True, "results": []}), "application/json; charset=utf-8"); return
                with _cache_lock:
                    files = list(_cache.get("files") or [])
                results = []
                for f in files:  # cache is already sorted by mtime desc
                    hay = (f["name"] + " " + f.get("rel_path", "")).lower()
                    if all(t in hay for t in terms):
                        results.append({
                            "name": f["name"], "path": f["path"],
                            "rel_path": f["rel_path"], "root": f["root"],
                            "icon": icon_for(f), "mtime_ago": time_ago(f["mtime"], lang),
                        })
                        if len(results) >= 100:
                            break
                self._send(json.dumps({"ok": True, "results": results, "total_scanned": len(files)}),
                           "application/json; charset=utf-8")
            elif path == "/api/browse":
                p = q.get("path", [None])[0]
                if not p:
                    self._send(json.dumps({"ok": False, "error": "missing path"}), "application/json; charset=utf-8"); return
                dpath = Path(p).expanduser().resolve()
                # Must be within a monitored target
                if not any(_path_is_within(dpath, t) for t in targets):
                    self.send_error(403, "Forbidden"); return
                if not dpath.exists() or not dpath.is_dir():
                    self._send(json.dumps({"ok": False, "error": "not a dir"}), "application/json; charset=utf-8"); return
                # Find monitored root for this directory
                root = None
                for t in targets:
                    if _path_is_within(dpath, t):
                        root = t
                        break
                payload = browse_dir(dpath, cap=5000)
                # Breadcrumbs: relative parts from monitored root
                crumbs = []
                if root is not None:
                    rel = dpath.relative_to(root)
                    cur = root
                    crumbs.append({"name": root.name or str(root), "path": str(root)})
                    for part in rel.parts:
                        cur = cur / part
                        crumbs.append({"name": part, "path": str(cur)})
                    # Add rel_path to each file so browse links carry full path from root
                    for finfo in payload.get("files", []):
                        finfo["rel_path"] = str(Path(finfo["path"]).relative_to(root))
                payload["breadcrumbs"] = crumbs
                payload["path"] = str(dpath)
                if root is not None:
                    payload["root"] = str(root)
                self._send(json.dumps(payload), "application/json; charset=utf-8")
            elif path == "/":
                # Reload config from disk to avoid stale state
                if not ephemeral:
                    _tm, _em, _xm = load_config(config_path)
                    with _state_lock:
                        _state[0], _state[1], _state[2] = _tm, _em, _xm
                with _cache_lock:
                    scanning = bool(_cache.get("scanning"))
                # Always re-scan in background to keep cache fresh
                if not scanning:
                    _start_scan_async()
                with _cache_lock:
                    files = list(_cache.get("files") or [])
                self._html(render_home(files, prefix, lang))
            elif path == "/view":
                f_rel = q.get("f", [None])[0]
                f_root = q.get("r", [None])[0]
                if not f_rel or not f_root:
                    self.send_error(404); return
                f_root_p = Path(f_root).expanduser().resolve()
                fpath = (f_root_p / f_rel).resolve()
                if not any(_path_is_within(f_root_p, t) for t in targets):
                    self.send_error(403, "Forbidden"); return
                try:
                    fpath.relative_to(f_root_p)
                except Exception:
                    self.send_error(403, "Forbidden"); return
                if fpath.exists() and fpath.is_file():
                    ext = fpath.suffix.lower()
                    if ext == ".md":
                        self._html(render_doc(fpath, prefix, lang, f_rel, f_root_p, mode="md"))
                    elif ext == ".txt":
                        self._html(render_doc(fpath, prefix, lang, f_rel, f_root_p, mode="txt"))
                    elif ext in MEDIA_EXTS:
                        self._html(render_media(fpath, prefix, lang))
                    else:
                        self._html(render_doc(fpath, prefix, lang, f_rel, f_root_p, mode="plain"))
                else:
                    self.send_error(404, "File not found")
            elif path == "/media":
                f_rel = q.get("f", [None])[0]
                f_root = q.get("r", [None])[0]
                if not f_rel or not f_root:
                    self.send_error(404); return
                f_root_p = Path(f_root).expanduser().resolve()
                fpath = (f_root_p / f_rel).resolve()
                if not any(_path_is_within(f_root_p, t) for t in targets):
                    self.send_error(403, "Forbidden"); return
                try:
                    fpath.relative_to(f_root_p)
                except Exception:
                    self.send_error(403, "Forbidden"); return
                if fpath.exists() and fpath.is_file():
                    self._send(fpath.read_bytes(), mime_for(fpath.name))
                else:
                    self.send_error(404, "File not found")
            elif path == "/download":
                f_rel = q.get("f", [None])[0]
                f_root = q.get("r", [None])[0]
                if not f_rel or not f_root:
                    self.send_error(404); return
                f_root_p = Path(f_root).expanduser().resolve()
                fpath = (f_root_p / f_rel).resolve()
                if not any(_path_is_within(f_root_p, t) for t in targets):
                    self.send_error(403, "Forbidden"); return
                try:
                    fpath.relative_to(f_root_p)
                except Exception:
                    self.send_error(403, "Forbidden"); return
                if fpath.exists() and fpath.is_file():
                    from urllib.parse import quote
                    ext = fpath.suffix.lower()
                    # RFC 5987: encode non-ASCII filenames for Content-Disposition
                    try:
                        fpath.name.encode('latin-1')
                        cd_fn = f'filename="{fpath.name}"'
                    except UnicodeEncodeError:
                        fn_enc = quote(fpath.name, safe='')
                        cd_fn = f'filename*=UTF-8\'\'{fn_enc}'
                    # Media gets its real MIME; text stays octet-stream so
                    # proxies (Caddy) don't rewrite the response
                    mime = mime_for(fpath.name) if ext in MEDIA_EXTS else "application/octet-stream"
                    body = fpath.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", mime)
                    self.send_header("Content-Disposition", f'attachment; {cd_fn}')
                    self.send_header("Content-Length", len(body))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_error(404, "File not found")
            else:
                self.send_error(404)

        def do_POST(self):
            if not self._authed():
                self.send_error(401, "Unauthorized")
                return
            parsed = urlparse(self.path)
            raw_path = parsed.path
            path = raw_path[len(prefix):] if prefix and raw_path.startswith(prefix) else raw_path
            if not path.startswith("/"):
                path = "/" + path
            if not _check_post_origin(self.headers):
                self.send_error(403, "Bad Origin"); return
            length = int(self.headers.get("Content-Length", 0))
            if length > 1024 * 1024:
                self.send_error(413, "Payload Too Large"); return
            body = self.rfile.read(length).decode("utf-8", errors="replace")
            try:
                data = json.loads(body) if body else {}
            except json.JSONDecodeError:
                data = {}
            targets, exclude_dirs, exclude_exts = _state

            # Sync in-memory state from disk before mutating (prevents stale overwrites)
            if not ephemeral and path.startswith("/api/") and path not in ("/api/version", "/api/dirs"):
                _disk_t, _disk_e, _disk_x = load_config(config_path)
                _state[0] = _disk_t
                _state[1] = _disk_e
                _state[2] = _disk_x
                targets, exclude_dirs, exclude_exts = _disk_t, _disk_e, _disk_x

            if path == "/api/refresh":
                _start_scan_async(force=True)
                self._send(json.dumps({"ok": True}), "application/json")
            elif path == "/api/favorites/toggle":
                fpath = data.get("path", "").strip()
                if not fpath:
                    self._send(json.dumps({"ok": False, "error": "missing path"}), "application/json"); return
                # Adding a new favorite must stay within monitored dirs
                # (removal is always allowed so stale entries can be cleaned).
                if fpath not in load_favorites(config_path):
                    fp_res = Path(fpath).expanduser()
                    if not any(_path_is_within(fp_res, t) for t in targets):
                        self._send(json.dumps({"ok": False, "error": "path not in monitored dirs"}), "application/json"); return
                action, favs = toggle_favorite(fpath, config_path)
                self._send(json.dumps({"ok": True, "action": action, "favorites": sorted(favs)}), "application/json")
            elif path == "/api/add-dir":
                d = data.get("dir", "").strip()
                if not d:
                    self._send(json.dumps({"ok": False, "error": "missing dir"}), "application/json"); return
                dp = Path(d).expanduser().resolve()
                if not dp.exists():
                    self._send(json.dumps({"ok": False, "error": f"not found: {dp}"}), "application/json"); return
                if dp in targets:
                    self._send(json.dumps({"ok": False, "error": "already exists"}), "application/json"); return
                targets.append(dp)
                save_config(targets, config_path, exclude_dirs, exclude_exts)
                self._send(json.dumps({"ok": True, "path": str(dp)}), "application/json")
            elif path == "/api/remove-dir":
                d = data.get("dir", "").strip()
                if not d:
                    self._send(json.dumps({"ok": False, "error": "missing dir"}), "application/json"); return
                dp = Path(d).expanduser().resolve()
                # Remove by matching resolved path
                _state[0] = [t for t in targets if t != dp]
                save_config(_state[0], config_path, exclude_dirs, exclude_exts)
                self._send(json.dumps({"ok": True}), "application/json")
            elif path == "/api/exclude-dir":
                d = data.get("dir", "").strip()
                if not d:
                    self._send(json.dumps({"ok": False, "error": "missing dir"}), "application/json"); return
                if d in exclude_dirs:
                    self._send(json.dumps({"ok": False, "error": "already excluded"}), "application/json"); return
                exclude_dirs.append(d)
                save_config(targets, config_path, exclude_dirs, exclude_exts)
                self._send(json.dumps({"ok": True, "exclude_dirs": exclude_dirs}), "application/json")
            elif path == "/api/remove-exclude-dir":
                d = data.get("dir", "").strip()
                if not d:
                    self._send(json.dumps({"ok": False, "error": "missing dir"}), "application/json"); return
                if d not in exclude_dirs:
                    self._send(json.dumps({"ok": False, "error": "not excluded"}), "application/json"); return
                _state[1] = [e for e in exclude_dirs if e != d]
                save_config(targets, config_path, _state[1], exclude_exts)
                self._send(json.dumps({"ok": True, "exclude_dirs": _state[1]}), "application/json")
            elif path == "/api/exclude-ext":
                ext = data.get("ext", "").strip()
                if not ext:
                    self._send(json.dumps({"ok": False, "error": "missing ext"}), "application/json"); return
                if not ext.startswith("."):
                    ext = "." + ext
                if ext in exclude_exts:
                    self._send(json.dumps({"ok": False, "error": "already excluded"}), "application/json"); return
                exclude_exts.append(ext)
                save_config(targets, config_path, exclude_dirs, exclude_exts)
                self._send(json.dumps({"ok": True, "exclude_exts": exclude_exts}), "application/json")
            elif path == "/api/remove-exclude-ext":
                ext = data.get("ext", "").strip()
                if not ext:
                    self._send(json.dumps({"ok": False, "error": "missing ext"}), "application/json"); return
                if not ext.startswith("."):
                    ext = "." + ext
                if ext not in exclude_exts:
                    self._send(json.dumps({"ok": False, "error": "not excluded"}), "application/json"); return
                _state[2] = [e for e in exclude_exts if e != ext]
                save_config(targets, config_path, exclude_dirs, _state[2])
                self._send(json.dumps({"ok": True, "exclude_exts": _state[2]}), "application/json")
            elif path == "/api/reload":
                new_targets, new_excludes, new_exclude_exts = load_config(config_path)
                _state[0] = new_targets
                _state[1] = new_excludes
                _state[2] = new_exclude_exts
                self._send(json.dumps({"ok": True, "count": len(new_targets)}), "application/json")
            elif path == "/api/upgrade":
                # Loopback always allowed; remote clients only when token auth
                # is enabled (and they already passed _authed above).
                if self.client_address[0] not in ("127.0.0.1", "::1") and not auth_token:
                    self.send_error(403, "Forbidden"); return
                try:
                    result = subprocess.run(
                        [sys.executable, "-m", "pip", "install", "--upgrade",
                         "git+https://github.com/zhixianio/owlia-nest.git"],
                        capture_output=True, text=True, timeout=60
                    )
                    ok = result.returncode == 0
                    msg = result.stdout.split("\n")[-3:] if ok else result.stderr[-200:]

                    if ok:
                        # Restart: kill our own PID after responding; launchd/systemd
                        # (KeepAlive/Restart=always) brings the upgraded code back up.
                        subprocess.Popen(
                            ["bash", "-c",
                             f"sleep 0.5; launchctl stop com.owlia.nest 2>/dev/null; kill {os.getpid()} 2>/dev/null; true"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True
                        )
                    self._send(json.dumps({"ok": ok, "output": "\n".join(msg),
                                           "restarting": ok}),
                                "application/json")
                except Exception as e:
                    self._send(json.dumps({"ok": False, "error": str(e)}),
                                "application/json")
            elif path == "/api/save":
                f_rel = data.get("f", "").strip()
                f_root = data.get("r", "").strip()
                content = data.get("content", "")
                if not f_rel or not f_root:
                    self._send(json.dumps({"ok": False, "error": "missing f/r"}), "application/json"); return
                f_root_p = Path(f_root).expanduser().resolve()
                fpath = (f_root_p / f_rel).resolve()
                if not any(_path_is_within(f_root_p, t) for t in targets):
                    self.send_error(403, "Forbidden"); return
                try:
                    fpath.relative_to(f_root_p)
                except Exception:
                    self.send_error(403, "Forbidden"); return
                if not fpath.exists() or not fpath.is_file():
                    self._send(json.dumps({"ok": False, "error": "file not found"}), "application/json"); return
                try:
                    fpath.write_text(content, encoding="utf-8")
                    # Clear file cache to pick up changes
                    with _cache_lock:
                        if "files" in _cache:
                            _cache["files"] = [f for f in _cache["files"] if f.get("path") != str(fpath)]
                    self._send(json.dumps({"ok": True}), "application/json")
                except Exception as e:
                    self._send(json.dumps({"ok": False, "error": str(e)}), "application/json")
            else:
                self.send_error(404)

        def _static(self, base, rel):
            try:
                fp = (base / rel).resolve()
                fp.relative_to(base.resolve())
            except Exception:
                self.send_error(404); return
            if not fp.is_file():
                self.send_error(404); return
            mime_map = {".css": "text/css", ".js": "application/javascript", ".mjs": "application/javascript",
                        ".png": "image/png", ".svg": "image/svg+xml", ".woff2": "font/woff2"}
            self._send(fp.read_bytes(), mime_map.get(fp.suffix.lower(), "application/octet-stream"))

        def _send(self, content, ct):
            body = content.encode("utf-8") if isinstance(content, str) else content
            self.send_response(200)
            if getattr(self, "_set_auth_cookie", False):
                self.send_header(
                    "Set-Cookie",
                    f"owlia_auth={auth_token}; Path=/; Max-Age=31536000; SameSite=Lax; HttpOnly")
            self.send_header("Content-Type", ct)
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)

        def _html(self, content):
            self._send(content, "text/html; charset=utf-8")

        def log_message(self, fmt, *args):
            pass

    return Handler


def serve(host="127.0.0.1", port=8788, prefix="", targets=None, ephemeral=False,
          auth_token=None):
    """Start the HTTP server."""
    from http.server import ThreadingHTTPServer
    if targets is None:
        targets = load_config()  # returns (dirs, excludes, exclude_exts)
    prefix = prefix.rstrip("/")
    if auth_token is None:
        auth_token = _read_config_raw().get("auth_token") or None

    Handler = create_app(targets, prefix, ephemeral=ephemeral, auth_token=auth_token)
    httpd = ThreadingHTTPServer((host, port), Handler)
    lock = " 🔒" if auth_token else ""
    print(f"🦉 Owlia Nest → http://{host}:{port}{prefix}/{lock}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Done")
        httpd.shutdown()
