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
from urllib.parse import parse_qs, urlparse
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
MAX_SCAN_DEPTH = 2
# Shared cache for scanned files (populated by background scanner).
FILE_CACHE = {}

# ── Security ──────────────────────────────────────────────────────
def _strip_html(raw: str) -> str:
    # Remove script/style blocks to avoid executing arbitrary JS/CSS when rendering markdown.
    raw = re.sub(r"(?is)<script[^>]*>.*?</script>", "", raw)
    raw = re.sub(r"(?is)<style[^>]*>.*?</style>", "", raw)
    return raw

# ── I18n ──────────────────────────────────────────────────────────
# Translation dictionary: Chinese key → {"zh": ..., "en": ...}
T = {
    # Brand / Header
    "Owlia Nest":           {"zh": "Owlia Nest", "en": "Owlia Nest"},
    "PA 产出文档中心":      {"zh": "PA 产出文档中心", "en": "PA Output Docs Hub"},

    # Categories
    "最近更新": {"zh": "最近更新", "en": "Recent"},
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


def _js_i18n(lang="zh"):
    """Generate a JS object literal with all translations for the given language."""
    entries = {k: v.get(lang, k) for k, v in T.items()}
    return json.dumps(entries, ensure_ascii=False)


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
  --tint: #ddf4ff;""",
    },
    "github-dark": {
        "name": "🌙 GitHub Dark",
        "css": """\
  --bg: #0d1117; --fg: #e6edf3; --accent: #58a6ff;
  --muted: #8b949e; --border: #30363d; --card-bg: #161b22; --code-bg: #161b22;
  --tint: #0c2d6b;""",
    },
    "nord": {
        "name": "❄️ Nord",
        "css": """\
  --bg: #2e3440; --fg: #d8dee9; --accent: #88c0d0;
  --muted: #81a1c1; --border: #4c566a; --card-bg: #3b4252; --code-bg: #3b4252;
  --tint: #434c5e;""",
    },
    "dracula": {
        "name": "🧛 Dracula",
        "css": """\
  --bg: #282a36; --fg: #f8f8f2; --accent: #bd93f9;
  --muted: #6272a4; --border: #44475a; --card-bg: #343746; --code-bg: #343746;
  --tint: #44475a;""",
    },
    "solarized": {
        "name": "📜 Solarized",
        "css": """\
  --bg: #fdf6e3; --fg: #657b83; --accent: #268bd2;
  --muted: #839496; --border: #93a1a1; --card-bg: #eee8d5; --code-bg: #eee8d5;
  --tint: #eee8d5;""",
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
        "has_update": latest is not None and latest != local,
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
    return f"""const CACHE = 'owlia-nest-v4-{prefix}';
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

BASE_CSS = """\
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: var(--bg); color: var(--fg); line-height: 1.6; transition: background 0.3s, color 0.3s; padding-top: env(safe-area-inset-top); padding-bottom: env(safe-area-inset-bottom); }
.container { max-width: 960px; margin: 0 auto; padding: 1rem 1.25rem; }
header { padding: 1.5rem 0; border-bottom: 1px solid var(--border); margin-bottom: 1.5rem; display: flex; align-items: baseline; justify-content: space-between; flex-wrap: wrap; gap: 0.5rem; }
header h1 { font-size: 1.5rem; color: var(--accent); }
header p { color: var(--muted); font-size: 0.85rem; }
.header-brand { display: flex; align-items: center; gap: 0.5rem; }
.header-brand h1 { margin: 0; }
.header-brand p { margin: 0; }
.logo { border-radius: 6px; flex-shrink: 0; }
.header-right { display: flex; gap: 0.5rem; align-items: center; }
.theme-select { font-size: 0.8rem; padding: 0.25rem 0.5rem; border: 1px solid var(--border); border-radius: 6px; background: var(--bg); color: var(--fg); cursor: pointer; font-family: inherit; }
.lang-toggle { font-size: 0.75rem; padding: 0.25rem 0.5rem; border: 1px solid var(--border); border-radius: 6px; background: var(--bg); color: var(--fg); cursor: pointer; font-family: inherit; white-space: nowrap; }
.lang-toggle:hover { border-color: var(--accent); }
.breadcrumb { font-size: 0.875rem; color: var(--muted); margin-bottom: 1rem; }
.breadcrumb a { color: var(--accent); text-decoration: none; }
.breadcrumb a:hover { text-decoration: underline; }
.browse-item { padding: 0.35rem 0.5rem; border-radius: 6px; cursor: pointer; transition: background 0.15s; user-select: none; }
.btn-dl { color: var(--muted); text-decoration: none; font-size: 0.85rem; padding: 0 0.2rem; flex-shrink: 0; }
.btn-dl:hover { color: var(--accent); }
.browse-item:hover { background: var(--card-bg); }
.browse-item a { color: var(--fg); text-decoration: none; }
.browse-item a:hover { color: var(--accent); }
.file-card { display: flex; align-items: baseline; gap: 0.75rem; padding: 0.6rem 0.5rem; border-bottom: 1px solid var(--border); border-radius: 6px; transition: background 0.15s; }
.file-card:hover { background: var(--card-bg); }
.btn-star { background: none; border: none; cursor: pointer; font-size: 1.15rem; padding: 0 0.25rem; flex-shrink: 0; opacity: 0.7; transition: opacity 0.15s; line-height: 1; color: #d4a017; }
.btn-star:hover { opacity: 0.8; }
.btn-star.faved { opacity: 1; }
.file-card:hover .btn-star { opacity: 0.75; }
.file-card:hover .btn-star:hover { opacity: 1; }
.file-icon { font-size: 1.1rem; flex-shrink: 0; width: 1.5rem; text-align: center; }
.file-name { flex: 1; min-width: 0; }
.file-name a { color: var(--accent); text-decoration: none; font-weight: 500; word-break: break-all; }
.file-name a:hover { text-decoration: underline; }
.file-path { color: var(--muted); font-size: 0.78rem; word-break: break-all; }
.file-date { color: var(--muted); font-size: 0.8rem; white-space: nowrap; min-width: 5rem; text-align: right; }
.file-size { color: var(--muted); font-size: 0.75rem; min-width: 3.5rem; text-align: right; }
.markdown-body { max-width: 100%; overflow-x: auto; word-wrap: break-word; }
.markdown-body h1 { font-size: 1.75rem; margin: 1.5rem 0 0.5rem; color: var(--fg); }
.markdown-body h2 { font-size: 1.35rem; margin: 1.25rem 0 0.4rem; padding-bottom: 0.3rem; border-bottom: 2px solid var(--border); color: var(--fg); }
.markdown-body h3 { font-size: 1.15rem; margin: 1rem 0 0.3rem; color: var(--fg); }
.markdown-body p, .markdown-body li { margin: 0.5rem 0; }
.markdown-body ul, .markdown-body ol { padding-left: 1.5rem; }
.markdown-body a { color: var(--accent); }
.markdown-body code { background: var(--code-bg); padding: 0.15em 0.4em; border-radius: 4px; font-size: 0.9em; }
.markdown-body pre { background: var(--code-bg); padding: 1rem; border-radius: 8px; overflow-x: auto; margin: 0.75rem 0; border: 1px solid var(--border); }
.markdown-body pre code { background: none; padding: 0; border: none; }
.markdown-body table { border-collapse: collapse; width: 100%; margin: 0.75rem 0; display: block; overflow-x: auto; }
.markdown-body th, .markdown-body td { border: 1px solid var(--border); padding: 0.5rem 0.75rem; text-align: left; }
.markdown-body th { background: var(--card-bg); font-weight: 600; }
.markdown-body blockquote { border-left: 3px solid var(--accent); padding: 0.5rem 1rem; color: var(--muted); margin: 0.75rem 0; background: var(--tint, var(--card-bg)); border-radius: 0 6px 6px 0; }
.markdown-body hr { border: none; border-top: 1px solid var(--border); margin: 1.5rem 0; }
.markdown-body img { max-width: 100%; height: auto; border-radius: 6px; }
.back-link { margin-top: 2rem; padding-top: 1rem; border-top: 1px solid var(--border); }
.back-link a { color: var(--accent); text-decoration: none; }
.status-bar { font-size: 0.75rem; color: var(--muted); text-align: center; padding: 1rem 0; margin-top: 2rem; border-top: 1px solid var(--border); }
.tabs-bar { display: flex; gap: 0.25rem; flex-wrap: wrap; margin-bottom: 1.5rem; border-bottom: 2px solid var(--border); padding-bottom: 0; }
.tabs-bar button { background: none; border: none; color: var(--muted); padding: 0.5rem 0.75rem; font-size: 0.875rem; cursor: pointer; border-bottom: 2px solid transparent; margin-bottom: -2px; transition: all 0.15s; font-family: inherit; }
.tabs-bar button:hover { color: var(--fg); }
.tabs-bar button.tab-active { color: var(--accent); border-bottom-color: var(--accent); font-weight: 600; }
.tab-count { font-size: 0.75rem; opacity: 0.6; }
.settings-panel { background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px; padding: 1rem; margin-bottom: 1.5rem; transition: all 0.2s; }
.settings-title { font-weight: 600; margin-bottom: 0.75rem; font-size: 0.95rem; }
.dir-list { display: flex; flex-direction: column; gap: 0.3rem; margin-bottom: 0.75rem; max-height: 200px; overflow-y: auto; }
.dir-item { display: flex; align-items: center; gap: 0.5rem; padding: 0.35rem 0.5rem; border-radius: 6px; font-size: 0.85rem; background: var(--bg); }
.dir-path { flex: 1; word-break: break-all; font-family: monospace; font-size: 0.78rem; }
.dir-remove { background: none; border: none; color: var(--muted); cursor: pointer; font-size: 1.1rem; padding: 0 0.25rem; line-height: 1; }
.dir-remove:hover { color: #ef4444; }
.add-dir-row { display: flex; gap: 0.5rem; }
.version-tag { font-size: 0.7rem; padding: 0.15rem 0.5rem; border-radius: 4px; background: var(--code-bg); color: var(--muted); border: 1px solid var(--border); white-space: nowrap; line-height: 1.4; }
.version-upgrade { font-size: 0.75rem; color: var(--accent); text-decoration: none; font-weight: 600; cursor: pointer; }
.version-upgrade:hover { text-decoration: underline; }
.upgrade-banner { margin: 0 0 1rem 0; padding: 0.6rem 1rem; background: var(--tint); border: 1px solid var(--accent); border-radius: 8px; font-size: 0.85rem; text-align: center; }
.upgrade-banner code { font-size: 0.78rem; background: var(--bg); padding: 0.15em 0.4em; border-radius: 4px; }
.dir-input { flex: 1; padding: 0.35rem 0.5rem; border: 1px solid var(--border); border-radius: 6px; background: var(--bg); color: var(--fg); font-family: monospace; font-size: 0.8rem; }
.dir-input:focus { outline: 2px solid var(--accent); }
.btn-add { padding: 0.35rem 0.75rem; border: 1px solid var(--accent); border-radius: 6px; background: var(--accent); color: #fff; cursor: pointer; font-size: 0.8rem; font-weight: 500; white-space: nowrap; }
.btn-add:hover { opacity: 0.85; }
.file-actions { position: absolute; right: 0.5rem; bottom: 0.3rem; display: flex; gap: 0.2rem; align-items: center; z-index: 1; }
.btn-tiny { font-size: 0.7rem; padding: 0.25rem 0.5rem; border: 1px solid var(--border); border-radius: 5px; background: var(--card-bg); color: var(--fg); cursor: pointer; touch-action: manipulation; }
.btn-tiny:hover { border-color: var(--accent); }
.file-card { position: relative; }
.exclude-list { display: flex; flex-wrap: wrap; gap: 0.3rem; margin-bottom: 0.5rem; }
.exclude-tag { display: inline-flex; align-items: center; gap: 0.2rem; padding: 0.15rem 0.5rem; border-radius: 6px; font-size: 0.78rem; background: var(--code-bg); border: 1px solid var(--border); }
@media (max-width: 600px) {
  .file-card { flex-wrap: wrap; gap: 0.3rem; }
  .file-date, .file-size { min-width: auto; }
  .container { padding: 0.5rem 0.75rem; }
  header { flex-direction: column; }
}
"""

# ── Page template ─────────────────────────────────────────────────
# Placeholders used in .format():
#   {lang_attr}    – HTML lang attribute ("zh-Hans" or "en")
#   {lang}         – language code for JS ("zh" or "en")
#   {__js_i18n__}  – JSON dict of all T entries in the current lang
#   {title} {body} {head_extra} {__theme_css__} {__theme_js__}
#   {BASE_CSS} {default_theme} {api_base}
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
{head_extra}
<style>
:root {{ {__theme_css__} }}
{BASE_CSS}
</style>
</head>
<body>
<div class="container">
{body}
</div>
<script>
var __LANG = '{lang}';
var I18N = {__js_i18n__};
function _(k){{ return I18N[k] || k; }}
function toggleLang(){{
  var n = __LANG === 'zh' ? 'en' : 'zh';
  document.cookie = 'lang=' + n + ';path=/;max-age=31536000';
  var u = new URL(location.href);
  u.searchParams.set('lang', n);
  location.href = u.toString();
}}
{__theme_js__}
(function(){{
  var sel=document.getElementById('themeSelect');
  if(sel){{
    var saved=localStorage.getItem('owlia-theme')||'{default_theme}';
    sel.value=saved;
    _apply(saved);
    sel.onchange=function(){{ _apply(this.value); localStorage.setItem('owlia-theme',this.value); }};
  }}
  function _apply(k){{
    var t=THEMES[k]; if(!t)return;
    var r=document.documentElement;
    Object.keys(t).forEach(function(v){{ r.style.setProperty('--'+v,t[v]); }});
    if(sel)sel.value=k;
  }}
  var btns=document.querySelectorAll('.tabs-bar button');
  btns.forEach(function(b){{
    b.onclick=function(){{
      btns.forEach(function(x){{x.classList.remove('tab-active')}});
      b.classList.add('tab-active');
      var key=b.dataset.tab;
      document.querySelectorAll('.tab-panel').forEach(function(p){{p.style.display='none'}});
      var el=document.querySelector('[data-panel="'+key+'"]');
      if(el)el.style.display='';
      if(key==='browse') initBrowse();
      if(key==='fav') renderFavTab();
      doSearch();
    }}
  }});
  /* Settings */
  /* loadDirs and loadFavorites moved to the init block below */
}})();
var _swReg = null;
if ('serviceWorker' in navigator) {{
  navigator.serviceWorker.register('{api_base}/sw.js').then(function(reg){{
    _swReg = reg;
    reg.onupdatefound = function(){{
      var newWorker = reg.installing;
      if (!newWorker) return;
      newWorker.onstatechange = function(){{
        if (newWorker.state === 'installed' && navigator.serviceWorker.controller) {{
          showUpdateToast();
        }}
      }};
    }};
    // Check for updates periodically
    setInterval(function(){{ reg.update(); }}, 60*1000);
  }});
  // Also detect update from controllerchange
  var refreshing = false;
  navigator.serviceWorker.oncontrollerchange = function(){{
    if (!refreshing) {{ refreshing = true; location.reload(); }}
  }};
}}
function showUpdateToast(){{
  var t = document.createElement('div');
  t.id = 'updateToast';
  t.style.cssText = 'position:fixed;bottom:1rem;right:1rem;background:var(--accent);color:#fff;padding:0.75rem 1rem;border-radius:8px;font-size:0.875rem;z-index:9999;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,0.3);';
  t.textContent = _('🔄 新版本可用，点击更新');
  t.onclick = function(){{
    if (_swReg && _swReg.waiting) {{ _swReg.waiting.postMessage('skip-waiting'); }}
    t.textContent = _('更新中…');
  }};
  document.body.appendChild(t);
}}
function showUpgradeCmd(e){{
  e.preventDefault();
  var b = document.getElementById('upgradeBanner');
  if(b) b.style.display = b.style.display === 'none' ? '' : 'none';
}}
function upgradeNow(){{
  var btn = document.querySelector('#upgradeBanner .btn-add');
  var status = document.getElementById('upgradeStatus');
  var status2 = document.getElementById('upgradeStatus2');
  if (btn) {{ btn.disabled = true; btn.textContent = _('⏳ 升级中…'); }}
  api('POST','{api_base}/api/upgrade',{{token:'owlia-upgrade-2026'}}).then(function(r){{
    if (r.ok) {{
      if (status) {{ status.textContent = _('✅ 升级完成，等待服务重启…'); status.style.color = '#22c55e'; }}
      if (status2) {{ status2.textContent = _('✅ 升级完成，等待服务重启…'); status2.style.color = '#22c55e'; }}
      // Poll for server to come back
      var attempts = 0;
      function poll() {{
        attempts++;
        fetch('{api_base}/').then(function(res){{
          if (res.ok) {{
            var el = status || status2;
            if (el) {{ el.innerHTML = _('✅ 服务已重启 ') + '<a href="#" onclick="location.reload()" style="color:var(--accent);text-decoration:underline">' + _('点击刷新') + '</a>'; }}
          }} else if (attempts < 30) {{ setTimeout(poll, 2000); }}
        }}).catch(function(){{
          if (attempts < 30) setTimeout(poll, 2000);
        }});
      }}
      setTimeout(poll, 3000);
    }} else {{
      if (status) {{ status.textContent = _('❌ 升级失败: ') + (r.error || r.output || _('未知错误')); status.style.color = '#ef4444'; }}
      if (status2) {{ status2.textContent = _('❌ 升级失败: ') + (r.error || r.output || _('未知错误')); status2.style.color = '#ef4444'; }}
      if (btn) {{ btn.disabled = false; btn.textContent = _('⚡ 一键升级'); }}
    }}
  }});
}}
// Legacy JS upgrade banner button
// Version check (GitHub releases)
setTimeout(checkVersion, 5000);
setInterval(checkVersion, 30*60*1000);
function checkVersion(){{
  api('GET','{api_base}/api/version').then(function(info){{
    if (info && info.has_update && info.latest) {{
      var id = 'upgradeBanner';
      if (document.getElementById(id)) return;
      var b = document.createElement('div');
      b.id = id;
      b.style.cssText = 'position:fixed;bottom:1rem;left:1rem;right:1rem;background:var(--bg);border:2px solid var(--accent);color:var(--fg);padding:0.75rem 1rem;border-radius:8px;font-size:0.875rem;z-index:9998;text-align:center;box-shadow:0 2px 12px rgba(0,0,0,0.2);max-width:500px;margin:0 auto;';
      b.innerHTML = '🆕 <strong>v'+info.latest+'</strong> ' + _('已发布（当前 v') + info.local + _('）') + '<br><button onclick="upgradeNow()" class="btn-add" style="margin:0.25rem 0">' + _('⚡ 一键升级') + '</button><br><small id="upgradeStatus2" style="color:var(--muted)"></small><br><button onclick="this.parentNode.remove()" style="margin-top:0.25rem;padding:0.15rem 0.5rem;border:1px solid var(--border);border-radius:6px;background:none;color:var(--muted);cursor:pointer;font-size:0.75rem">' + _('忽略') + '</button>';
      document.body.appendChild(b);
    }}
  }});
}}
</script>
<script>
function toggleSettings(){{
  var p=document.getElementById('settingsPanel');
  p.style.display=p.style.display==='none'?'block':'none';
  if(p.style.display==='block')loadDirs();
}}
function api(method,url,body){{ return fetch(url,{{method:method,headers:{{'Content-Type':'application/json'}},body:body?JSON.stringify(body):null}}).then(function(r){{ if(!r.ok)throw new Error(r.status); return r.json(); }}); }}
function loadDirs(){{
  api('GET','{api_base}/api/dirs').then(function(data){{
    var dirs = Array.isArray(data) ? data : data.dirs || [];
    var excludeDirs = data.exclude_dirs || [];
    var excludeExts = data.exclude_exts || [];
    var el=document.getElementById('dirList');
    if(el){{ el.innerHTML=dirs.map(function(d){{ return '<div class="dir-item"><span class="dir-path">'+d+'</span><button class="dir-remove" data-dir="'+encodeURIComponent(d)+'" title="'+_('移除')+'">×</button></div>'; }}).join('')||'<span style="color:var(--muted);font-size:0.8rem">'+_('暂无监控目录')+'</span>'; }}
    var exEl=document.getElementById('excludeDirList');
    if(exEl){{ exEl.innerHTML=excludeDirs.map(function(d){{ return '<span class="exclude-tag">📁 '+d+' <button class="dir-remove" data-exdir="'+encodeURIComponent(d)+'" title="'+_('移除排除')+'">×</button></span>'; }}).join('')||'<span style="color:var(--muted);font-size:0.75rem">'+_('无')+'</span>'; }}
    var extEl=document.getElementById('excludeExtList');
    if(extEl){{ extEl.innerHTML=excludeExts.map(function(e){{ return '<span class="exclude-tag">'+e+' <button class="dir-remove" data-exext="'+encodeURIComponent(e)+'" title="'+_('移除排除')+'">×</button></span>'; }}).join('')||'<span style="color:var(--muted);font-size:0.75rem">'+_('无')+'</span>'; }}
    // Attach handlers
    document.querySelectorAll('.dir-remove[data-dir]').forEach(function(btn){{ btn.onclick=function(){{ removeDir(decodeURIComponent(this.dataset.dir)); }}; }});
    document.querySelectorAll('.dir-remove[data-exdir]').forEach(function(btn){{ btn.onclick=function(){{ removeExcludeDir(decodeURIComponent(this.dataset.exdir)); }}; }});
    document.querySelectorAll('.dir-remove[data-exext]').forEach(function(btn){{ btn.onclick=function(){{ removeExcludeExt(decodeURIComponent(this.dataset.exext)); }}; }});
  }});
}}
function addDir(){{
  var inp=document.getElementById('dirInput');
  if(!inp||!inp.value.trim())return;
  api('POST','{api_base}/api/add-dir',{{dir:inp.value.trim()}}).then(function(r){{
    if(r.ok){{ inp.value=''; loadDirs(); setTimeout(function(){{location.reload()}},500); }}
    else alert(r.error||'Failed');
  }});
}}
function removeDir(d){{
  d=decodeURIComponent(d);
  if(!confirm(_('移除 ') + d + _(' ？')))return;
  api('POST','{api_base}/api/remove-dir',{{dir:d}}).then(function(r){{
    if(r.ok){{ loadDirs(); setTimeout(function(){{location.reload()}},500); }}
    else alert(r.error||'Failed');
  }});
}}
function addExcludeDir(){{
  var inp=document.getElementById('excludeDirInput');
  if(!inp||!inp.value.trim())return;
  api('POST','{api_base}/api/exclude-dir',{{dir:inp.value.trim()}}).then(function(r){{
    if(r.ok){{ inp.value=''; loadDirs(); setTimeout(function(){{location.reload()}},500); }}
    else alert(r.error||'Failed');
  }});
}}
function removeExcludeDir(d){{
  d=decodeURIComponent(d);
  api('POST','{api_base}/api/remove-exclude-dir',{{dir:d}}).then(function(r){{
    if(r.ok){{ loadDirs(); setTimeout(function(){{location.reload()}},500); }}
    else alert(r.error||'Failed');
  }});
}}
function addExcludeExt(){{
  var inp=document.getElementById('excludeExtInput');
  if(!inp||!inp.value.trim())return;
  api('POST','{api_base}/api/exclude-ext',{{ext:inp.value.trim()}}).then(function(r){{
    if(r.ok){{ inp.value=''; loadDirs(); setTimeout(function(){{location.reload()}},500); }}
    else alert(_('添加失败: ') + (r.error || _('未知错误')));
  }});
}}
function quickExcludeDir(name,btn){{
  if (btn.textContent === _('↩ 撤销')) {{
    api('POST','{api_base}/api/remove-exclude-dir',{{dir:name}}).then(function(r){{
      if(r.ok){{ toast(_('已恢复目录: ')+name); setTimeout(function(){{location.reload()}},800); }}
      else alert(r.error||_('操作失败'));
    }}).catch(function(e){{ alert(_('网络错误: ')+e); }});
  }} else {{
    toast(_('将排除目录: ')+name+_('\\n（相同目录下的其他文件也会一并隐藏）'));
    api('POST','{api_base}/api/exclude-dir',{{dir:name}}).then(function(r){{
      if(r.ok){{ btn.textContent=_('↩ 撤销'); btn.title=_('↩ 撤销'); toast(_('✅ 已排除目录: ')+name); setTimeout(function(){{location.reload()}},1200); }}
      else alert(r.error||_('操作失败'));
    }}).catch(function(e){{ alert(_('网络错误: ')+e); }});
  }}
}}
function quickExcludeExt(ext,btn){{
  if (btn.textContent === _('↩ 撤销')) {{
    api('POST','{api_base}/api/remove-exclude-ext',{{ext:ext}}).then(function(r){{
      if(r.ok){{ toast(_('已恢复类型: ')+ext); setTimeout(function(){{location.reload()}},800); }}
      else alert(r.error||_('操作失败'));
    }}).catch(function(e){{ alert(_('网络错误: ')+e); }});
  }} else {{
    toast(_('将排除类型: ')+ext+_('\\n（所有同扩展名文件都会被隐藏）'));
    api('POST','{api_base}/api/exclude-ext',{{ext:ext}}).then(function(r){{
      if(r.ok){{ btn.textContent=_('↩ 撤销'); btn.title=_('↩ 撤销'); toast(_('✅ 已排除类型: ')+ext); setTimeout(function(){{location.reload()}},1200); }}
      else alert(r.error||_('操作失败'));
    }}).catch(function(e){{ alert(_('网络错误: ')+e); }});
  }}
}}
function toast(msg){{
  var id='_toast'; var e=document.getElementById(id); if(e)e.remove();
  e=document.createElement('div'); e.id=id;
  e.style.cssText='position:fixed;bottom:2rem;left:50%;transform:translateX(-50%);background:var(--fg);color:var(--bg);padding:0.6rem 1.2rem;border-radius:8px;font-size:0.85rem;z-index:9999;white-space:pre-line;text-align:center;box-shadow:0 4px 16px rgba(0,0,0,0.3);transition:opacity 0.3s';
  e.textContent=msg; document.body.appendChild(e);
  setTimeout(function(){{ e.style.opacity='0'; setTimeout(function(){{if(e.parentNode)e.remove()}},300); }},2500);
}}
var _browseState = {{ path: null, inited: false, dirs: [] }};
var _favorites = new Set();
function loadFavorites(){{
  // Load from localStorage first for instant UI
  try{{
    var local=localStorage.getItem('owlia-nest-favs');
    if(local){{ _favorites=new Set(JSON.parse(local)); }}
  }}catch(e){{}}
  renderStars();
  updateFavCount();
  // Then sync from server
  api('GET','{api_base}/api/favorites').then(function(data){{
    if(data && data.favorites){{ _favorites=new Set(data.favorites); }}
    renderStars();
    updateFavCount();
    try{{ localStorage.setItem('owlia-nest-favs',JSON.stringify([..._favorites])); }}catch(e){{}}
  }}).catch(function(){{
    setTimeout(function(){{
      api('GET','{api_base}/api/favorites').then(function(data){{
        if(data && data.favorites){{ _favorites=new Set(data.favorites); }}
        renderStars();
        updateFavCount();
        try{{ localStorage.setItem('owlia-nest-favs',JSON.stringify([..._favorites])); }}catch(e){{}}
      }});
    }},500);
  }});
}}
function toggleFav(fpath,starEl){{
  // Optimistic UI update
  var wasFaved = _favorites.has(fpath);
  if(wasFaved){{
    _favorites.delete(fpath); starEl.textContent='☆'; starEl.classList.remove('faved'); starEl.title=_('收藏');
  }} else {{
    _favorites.add(fpath); starEl.textContent='⏳'; starEl.classList.add('faved'); starEl.title=_('取消收藏');
  }}
  updateFavCount();
  try{{ localStorage.setItem('owlia-nest-favs',JSON.stringify([..._favorites])); }}catch(e){{}}
  api('POST','{api_base}/api/favorites/toggle',{{path:fpath}}).then(function(r){{
    if(r && r.ok){{ starEl.textContent='⭐'; return; }}
    throw new Error('api failed');
  }}).catch(function(){{
    if(wasFaved){{ _favorites.add(fpath); starEl.textContent='⭐'; starEl.classList.add('faved'); starEl.title=_('取消收藏'); }}
    else{{ _favorites.delete(fpath); starEl.textContent='☆'; starEl.classList.remove('faved'); starEl.title=_('收藏'); }}
    updateFavCount();
    try{{ localStorage.setItem('owlia-nest-favs',JSON.stringify([..._favorites])); }}catch(e){{}}
  }});
}}
function renderStars(){{
  document.querySelectorAll('.btn-star').forEach(function(star){{
    var fpath = star.dataset.filepath;
    if(!fpath) return;
    if(_favorites.has(fpath)){{
      star.textContent='⭐'; star.classList.add('faved'); star.title=_('取消收藏');
    }} else {{
      star.textContent='☆'; star.classList.remove('faved'); star.title=_('收藏');
    }}
  }});
}}
function updateFavCount(){{
  var btn=document.querySelector('.tabs-bar button[data-tab="fav"]');
  if(btn){{ var cnt=btn.querySelector('.tab-count'); if(cnt) cnt.textContent=_favorites.size; }}
}}
function renderFavTab(){{
  var panel=document.querySelector('[data-panel="fav"]');
  if(!panel) return;
  var seen=new Set();
  var html='';
  document.querySelectorAll('.file-card').forEach(function(card){{
    var a=card.querySelector('.file-name a');
    if(!a||!a.dataset.filepath) return;
    if(!_favorites.has(a.dataset.filepath)) return;
    if(seen.has(a.dataset.filepath)) return;
    seen.add(a.dataset.filepath);
    html+=card.outerHTML;
  }});
  panel.innerHTML=html||'<p style="color:var(--muted);padding:2rem;text-align:center">'+_('暂无内容')+'</p>';
}}
function initBrowse(){{
  if(_browseState.inited) return;
  _browseState.inited = true;
  api('GET','{api_base}/api/dirs').then(function(info){{
    var dirs = (info && info.dirs) ? info.dirs : [];
    if(dirs.length===0) return;
    _browseState.dirs = dirs;
    renderBrowseRoot(dirs);
  }}).catch(function(){{}});
}}
function renderBrowseRoot(dirs){{
  var bcEl = document.getElementById('browseBreadcrumbs');
  var listEl = document.getElementById('browseList');
  if(!bcEl || !listEl) return;
  bcEl.innerHTML = '<span style="color:var(--muted)">📂 '+_('监控目录')+'</span>';
  var h = '';
  for(var j=0;j<dirs.length;j++){{
    var d=dirs[j];
    h += '<div class="browse-item" data-browse-path="'+escapeHtml(d)+'">📁 '+escapeHtml(d)+'</div>';
  }}
  listEl.innerHTML = h;
  doSearch();
}}
function loadBrowse(p){{
  if(!p) return;
  _browseState.path = p;
  var url = '{api_base}/api/browse?path=' + encodeURIComponent(p);
  fetch(url).then(function(r){{ return r.json(); }}).then(function(data){{
    renderBrowse(data);
  }}).catch(function(e){{
    var el = document.getElementById('browseList');
    if(el) el.innerHTML = '<p style="color:var(--muted)">'+escapeHtml(String(e))+'</p>';
  }});
}}
function renderBrowse(data){{
  var bcEl = document.getElementById('browseBreadcrumbs');
  var listEl = document.getElementById('browseList');
  if(!bcEl || !listEl) return;
  if(!data || !data.ok){{
    bcEl.innerHTML = '';
    listEl.innerHTML = '<p style="color:var(--muted)">'+escapeHtml((data&&data.error)||'Failed')+'</p>';
    return;
  }}
  var bcs = data.breadcrumbs || [];
  var bcHtml = '<a href="#" class="browse-item" data-browse-root="1">📂 '+_('监控目录')+'</a>';
  for(var i=0;i<bcs.length;i++){{ 
    var c=bcs[i];
    bcHtml += ' / <a href="#" class="browse-item" data-browse-path="'+escapeHtml(c.path)+'">'+escapeHtml(c.name)+'</a>';
  }}
  bcEl.innerHTML = bcHtml;
  var ds = data.dirs || [];
  var fs = data.files || [];
  var h = '';
  for(var j=0;j<ds.length;j++){{ 
    var d=ds[j];
    h += '<div class="browse-item" data-browse-path="'+escapeHtml(d.path)+'">📁 '+escapeHtml(d.name)+'</div>';
  }}
  for(var k=0;k<fs.length;k++){{ 
    var f=fs[k];
    var href = '{api_base}/view?f=' + encodeURIComponent(f.name) + '&r=' + encodeURIComponent(data.path);
    h += '<div class="browse-item">📄 <a href="'+href+'">'+escapeHtml(f.name)+'</a></div>';
  }}
  listEl.innerHTML = h || '<p style="color:var(--muted)">'+_('暂无内容')+'</p>';
  doSearch();
}}
function doSearch(){{
  var inp = document.getElementById('searchInput');
  var q = (inp && inp.value) ? inp.value.trim().toLowerCase() : '';
  var activeBtn = document.querySelector('.tabs-bar button.tab-active');
  var key = activeBtn ? activeBtn.getAttribute('data-tab') : 'recent';
  var panel = document.querySelector('[data-panel=\"'+key+'\"]');
  if(!panel) return;
  var items = panel.querySelectorAll('.file-card, .browse-item');
  for(var i=0;i<items.length;i++){{ 
    var it=items[i];
    if(!q){{ it.style.display=''; continue; }}
    var t = (it.textContent||'').toLowerCase();
    it.style.display = (t.indexOf(q) >= 0) ? '' : 'none';
  }}
}}
// Delegated click handler for exclude buttons
document.addEventListener('click',function(e){{
  // Browse root handler — go back to monitored dirs list
  var r = e.target.closest('[data-browse-root]');
  if(r){{ e.preventDefault(); renderBrowseRoot(_browseState.dirs); return; }}
  // Browse path handler — check FIRST, before .btn-tiny
  var b = e.target.closest('[data-browse-path]');
  if(b){{ e.preventDefault(); loadBrowse(b.getAttribute('data-browse-path')); return; }}
  var btn = e.target.closest('.btn-tiny');
  if(!btn) return;
  var d = btn.getAttribute('data-exclude-dir');
  if(d){{ quickExcludeDir(d,btn); return; }}
  var ext = btn.getAttribute('data-exclude-ext');
  if(ext){{ quickExcludeExt(ext,btn); return; }}
}});
function removeExcludeExt(e){{
  e=decodeURIComponent(e);
  api('POST','{api_base}/api/remove-exclude-ext',{{ext:e}}).then(function(r){{
    if(r.ok){{ loadDirs(); setTimeout(function(){{location.reload()}},500); }}
    else alert(r.error||'Failed');
  }});
}}
/* Init: call after all functions are defined */
(function(){{
  loadDirs();
  loadFavorites();
}})();
</script>
</body>
</html>
"""

CATEGORIES = {
    "recent": ("🕐", "最近更新"), "doc": ("📄", "文档"),
    "code": ("💻", "代码"), "config": ("⚙️", "配置"), "media": ("🎬", "媒体"),
    "fav": ("⭐", "收藏"),
    "browse": ("📁", "浏览"),
}
_FILE_ICON = {
    "md": "📄", "txt": "📝",
    "py": "🐍", "ts": "🔷", "js": "📜", "html": "🌐", "css": "🎨",
    "json": "⚙️", "yaml": "⚙️", "yml": "⚙️", "toml": "⚙️",
    "png": "🖼️", "jpg": "🖼️", "jpeg": "🖼️", "gif": "🖼️", "webp": "🖼️", "svg": "🖼️",
    "mp3": "🎵", "wav": "🎵", "ogg": "🎵", "m4a": "🎵", "opus": "🎵",
}

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

def load_config(config_path=None):
    if config_path is None:
        config_path = Path.home() / ".config" / "owlia-nest" / "dirs.json"
    path = _expand(config_path)
    if path.exists():
        data = json.loads(path.read_text())
        dirs = [_expand(p) for p in data.get("dirs", [])]
        excludes = data.get("exclude_dirs", [])
        exclude_exts = data.get("exclude_exts", [])
        return dirs, excludes, exclude_exts
    # fallback: scan default dirs if they exist
    dirs = [_expand(d) for d in DEFAULT_DIRS if _expand(d).exists()]
    return dirs, [], []

def save_config(dirs, config_path=None, exclude_dirs=None, exclude_exts=None):
    if config_path is None:
        config_path = Path.home() / ".config" / "owlia-nest" / "dirs.json"
    path = _expand(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text())
        except Exception:
            pass
    # Build new data preserving any keys from existing that aren't being overridden
    data = {"dirs": [str(d) for d in dirs]}
    data["exclude_dirs"] = exclude_dirs if exclude_dirs is not None else existing.get("exclude_dirs", [])
    data["exclude_exts"] = exclude_exts if exclude_exts is not None else existing.get("exclude_exts", [])
    path.write_text(json.dumps(data, indent=2))
    return path

def load_favorites(config_path=None):
    """Load favorited file paths from config."""
    if config_path is None:
        config_path = Path.home() / ".config" / "owlia-nest" / "dirs.json"
    path = _expand(config_path)
    if path.exists():
        try:
            data = json.loads(path.read_text())
            return set(data.get("favorites", []))
        except Exception:
            pass
    return set()

def save_favorites(favorites, config_path=None):
    """Save favorited file paths to config."""
    if config_path is None:
        config_path = Path.home() / ".config" / "owlia-nest" / "dirs.json"
    path = _expand(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text())
        except Exception:
            pass
    existing["favorites"] = sorted(favorites)
    path.write_text(json.dumps(existing, indent=2))
    return path

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

def scan_files(targets, exclude_dirs=None, exclude_exts=None):
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
    valid_ext = {".md", ".txt", ".py", ".ts", ".js", ".html", ".css", ".json", ".yaml", ".yml", ".toml",
                 ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
                 ".mp3", ".wav", ".ogg", ".m4a", ".opus"}
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
                MAX_SCAN_DEPTH,
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
    name = f["name"]
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext in ("md", "txt"): return "doc"
    if ext in ("py", "ts", "js", "tsx", "jsx", "html", "css", "scss"): return "code"
    if ext in ("json", "yaml", "yml", "toml", "cfg", "ini", "env", "lock"): return "config"
    if ext in ("png", "jpg", "jpeg", "gif", "webp", "svg", "mp3", "wav", "ogg", "m4a", "opus"): return "media"
    return "other"

def icon_for(f):
    name = f["name"]
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return _FILE_ICON.get(ext, "📁" if f["is_dir"] else "📎")

# ── HTML builders ─────────────────────────────────────────────────
def mk_page(title, body, head_extra="", default_theme="github-dark", prefix="", lang="zh"):
    theme_css = THEMES[default_theme]["css"].strip()
    theme_json = json.dumps({k: theme_dict(k) for k in THEMES})
    theme_js = f"var THEMES = {theme_json};"
    # Inject helpers via head_extra (do NOT put these inside PAGE_TPL).
    head_extra = (
        "<script>"
        "function escapeHtml(s){"
        "s=(s===null||s===undefined)?'':String(s);"
        "return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')"
        ".replace(/\\\"/g,'&quot;').replace(/'/g,'&#39;');"
        "}"
        "</script>"
        + (head_extra or "")
    )
    return PAGE_TPL.format(
        title=title, body=body, head_extra=head_extra,
        __theme_css__=theme_css, __theme_js__=theme_js,
        BASE_CSS=BASE_CSS, default_theme=default_theme,
        api_base=prefix,
        lang_attr=_lang_attr(lang), lang=lang,
        __js_i18n__=_js_i18n(lang),
    )

def file_card(f, href, lang="zh"):
    dname = os.path.dirname(f["path"])
    fpath = f["path"]
    ext = f["name"].rsplit(".", 1)[-1].lower() if "." in f["name"] else ""
    safe_name = escape(f["name"])
    safe_fpath = escape(fpath)
    return (
        f'<div class="file-card" data-cat="{classify(f)}">'
        f'<span class="file-icon">{icon_for(f)}</span>'
        f'<button class="btn-star" data-filepath="{escape(fpath)}" title="{_("收藏", lang)}" onclick="event.preventDefault();event.stopPropagation();toggleFav(this.dataset.filepath,this)">☆</button>'
        f'<span class="file-name"><a href="{href}?f={f["rel_path"]}&r={f["root"]}" data-filepath="{escape(fpath)}">{safe_name}</a>'
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
    body = header + tabs + "\n".join(secs)
    return mk_page("Owlia Nest", body, head_extra, prefix=prefix, lang=lang)

def render_md(path, prefix="", lang="zh", f_rel=None, f_root=None):
    raw = path.read_text(encoding="utf-8", errors="replace")
    raw = _strip_html(raw)
    html = markdown.markdown(raw, extensions=MD_EXTENSIONS)
    from urllib.parse import quote
    safe_url = quote(path.name)
    dl_url = f"{prefix}/download?f={safe_url}&r={path.parent}"
    theme_opts = "".join(f'<option value="{k}">{v["name"]}</option>' for k, v in THEMES.items())
    safe_name = escape(path.name)
    # Embed raw md as JSON (handles all Unicode safely)
    raw_json = json.dumps(raw)
    f_rel_s = escape(f_rel or path.name)
    f_root_s = escape(str(f_root or path.parent))
    save_text = _("保存", lang)
    editor_js = """<link rel="stylesheet" href="%s/icons/easymde.css">
<script src="%s/icons/easymde.js"></script>
<style>
#mdEditor { margin: 1rem 0; }
.btn-edit { background: none; border: 1px solid var(--border); border-radius: 6px; padding: 2px 8px; cursor: pointer; font-size: 0.85rem; color: var(--fg); margin-left: 4px; }
.btn-edit:hover { background: var(--accent); color: #fff; border-color: var(--accent); }
/* EasyMDE Owlia Nest theme */
.EasyMDEContainer .CodeMirror { background: var(--card-bg); color: var(--fg); border-color: var(--border); }
.EasyMDEContainer .editor-toolbar { background: var(--card-bg); border-color: var(--border); }
.EasyMDEContainer .editor-toolbar button { color: var(--fg); }
.EasyMDEContainer .editor-toolbar button:hover,
.EasyMDEContainer .editor-toolbar button.active { background: var(--tint); border-color: var(--accent); }
.EasyMDEContainer .editor-toolbar i.separator { border-left-color: var(--border); border-right-color: transparent; }
.EasyMDEContainer .editor-preview { background: var(--bg); color: var(--fg); }
.EasyMDEContainer .editor-preview pre { background: var(--code-bg); }
.EasyMDEContainer .editor-statusbar { color: var(--muted); }
.EasyMDEContainer .CodeMirror-gutters { background: var(--code-bg); border-right-color: var(--border); color: var(--muted); }
.EasyMDEContainer .CodeMirror-linenumber { color: var(--muted); }
.EasyMDEContainer .CodeMirror-cursor { border-left-color: var(--accent); }
.EasyMDEContainer .CodeMirror-selected { background: var(--tint) !important; }
.EasyMDEContainer .CodeMirror-focused .CodeMirror-selected { background: var(--tint) !important; }
.EasyMDEContainer .CodeMirror-fullscreen { background: var(--bg); }
.EasyMDEContainer .editor-toolbar.fullscreen { background: var(--bg); }
.EasyMDEContainer .editor-toolbar.fullscreen::before,
.EasyMDEContainer .editor-toolbar.fullscreen::after { background: none; }
.EasyMDEContainer .CodeMirror-placeholder { color: var(--muted); }
.cm-s-easymde .cm-header { color: var(--accent); }
.cm-s-easymde .cm-link { color: var(--accent); }
.cm-s-easymde .cm-url { color: var(--muted); }
.cm-s-easymde .cm-quote { color: var(--muted); }
.cm-s-easymde .cm-comment { background: var(--code-bg); color: var(--muted); }
.cm-s-easymde .cm-string { color: #a5d6ff; }
.cm-s-easymde .cm-tag { color: #7ee787; }
.cm-s-easymde .cm-attribute { color: #d2a8ff; }
.easymde-dropdown-content { background: var(--card-bg); border: 1px solid var(--border); }
.easymde-dropdown-content button { color: var(--fg); }
.easymde-dropdown-content button:hover { background: var(--tint); }
.editor-toolbar .easymde-dropdown { border-color: var(--fg); }
.CodeMirror div.CodeMirror-cursors { visibility: visible; }
</style>
<script>
var _easyMDE = null;
var _mdRaw = null;
var _mdFile = { f: '%s', r: '%s' };
var _mdPrefix = '%s';
var _saveLabel = '%s';
function toggleEdit() {
  if (!_mdRaw) {
    try { _mdRaw = JSON.parse(document.getElementById('mdRawData').textContent); } catch(e) {}
    if (!_mdRaw) _mdRaw = '';
  }
  document.getElementById('mdView').style.display = 'none';
  document.getElementById('mdEditor').style.display = '';
  document.getElementById('btnEdit').style.display = 'none';
  document.getElementById('btnSave').style.display = '';
  document.getElementById('btnCancel').style.display = '';
  if (!_easyMDE) {
    _easyMDE = new EasyMDE({
      element: document.getElementById('mdTextarea'),
      initialValue: _mdRaw,
      spellChecker: false,
      status: false,
      autosave: { enabled: false },
      renderingConfig: { codeSyntaxHighlighting: true }
    });
  } else {
    _easyMDE.value(_mdRaw);
  }
}
function cancelEdit() {
  document.getElementById('mdView').style.display = '';
  document.getElementById('mdEditor').style.display = 'none';
  document.getElementById('btnEdit').style.display = '';
  document.getElementById('btnSave').style.display = 'none';
  document.getElementById('btnCancel').style.display = 'none';
}
function saveEdit() {
  var content = _easyMDE ? _easyMDE.value() : '';
  var btn = document.getElementById('btnSave');
  btn.disabled = true;
  btn.textContent = '⏳';
  fetch(_mdPrefix + '/api/save', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ f: _mdFile.f, r: _mdFile.r, content: content })
  }).then(function(r){ return r.json(); }).then(function(r) {
    if (r.ok) {
      _mdRaw = content;
      // Update rendered view in-place by re-fetching the view page
      var viewUrl = _mdPrefix + '/view?f=' + encodeURIComponent(_mdFile.f) + '&r=' + encodeURIComponent(_mdFile.r);
      fetch(viewUrl).then(function(resp){ return resp.text(); }).then(function(html) {
        var tmp = document.createElement('div');
        tmp.innerHTML = html;
        var newView = tmp.querySelector('#mdView');
        if (newView) {
          document.getElementById('mdView').innerHTML = newView.innerHTML;
        }
        // Stay in edit mode — just update the button to show success
        btn.textContent = '✅ ' + _saveLabel;
        setTimeout(function() { btn.textContent = '💾 ' + _saveLabel; }, 1200);
        btn.disabled = false;
      }).catch(function() {
        btn.textContent = _saveLabel;
        btn.disabled = false;
      });
    } else {
      alert(r.error || 'Save failed');
      btn.textContent = _saveLabel;
      btn.disabled = false;
    }
  }).catch(function(e) {
    alert('Network error: ' + e);
    btn.textContent = _saveLabel;
    btn.disabled = false;
  });
}
/* Keyboard shortcut: Ctrl+S / Cmd+S → save (stay in editor) */
document.addEventListener('keydown', function(e) {
  if ((e.ctrlKey || e.metaKey) && e.key === 's') {
    e.preventDefault();
    var saveBtn = document.getElementById('btnSave');
    if (saveBtn && saveBtn.style.display !== 'none') {
      saveEdit();
    }
  }
});
</script>
<script type="application/json" id="mdRawData">%s</script>
""" % (prefix, prefix, f_rel_s, f_root_s, prefix, save_text, raw_json)
    body = f"""<header><div class="header-brand"><img src="{prefix}/icons/logo.png" alt="Owlia Nest" class="logo" width="32" height="32"><h1>Owlia Nest</h1></div>
  <div class="header-right">
    <button class="lang-toggle" onclick="toggleLang()" title="中 | EN">{_("中 | EN", lang)}</button>
    <select class="theme-select" id="themeSelect">{theme_opts}</select></div></header>
<div class="breadcrumb"><a href="{prefix}/">{_("← Home", lang)}</a> / {safe_name} <a href="{dl_url}" class="btn-dl" title="{_('下载', lang)}">⬇</a> <button id="btnEdit" class="btn-edit" title="{_('编辑', lang)}" onclick="toggleEdit()">✏️ {_('编辑', lang)}</button><button id="btnSave" class="btn-edit" title="{_('保存', lang)}" onclick="saveEdit()" style="display:none">💾 {_('保存', lang)}</button><button id="btnCancel" class="btn-edit" title="{_('取消', lang)}" onclick="cancelEdit()" style="display:none">❌ {_('取消', lang)}</button></div>
<div id="mdView" class="markdown-body">{html}</div>
<div id="mdEditor" style="display:none"><textarea id="mdTextarea"></textarea></div>
<div class="back-link"><a href="{prefix}/">{_("← 返回首页", lang)}</a></div>"""
    return mk_page(f"{safe_name} — Owlia Nest", body, editor_js, prefix=prefix, lang=lang)

def render_txt(path, prefix="", lang="zh"):
    raw = path.read_text(encoding="utf-8", errors="replace")
    raw = escape(raw)
    from urllib.parse import quote
    safe_url = quote(path.name)
    dl_url = f"{prefix}/download?f={safe_url}&r={path.parent}"
    theme_opts = "".join(f'<option value="{k}">{v["name"]}</option>' for k, v in THEMES.items())
    safe_name = escape(path.name)
    body = f"""<header><div class="header-brand"><img src="{prefix}/icons/logo.png" alt="Owlia Nest" class="logo" width="32" height="32"><h1>Owlia Nest</h1></div>
  <div class="header-right">
    <button class="lang-toggle" onclick="toggleLang()" title="中 | EN">{_("中 | EN", lang)}</button>
    <select class="theme-select" id="themeSelect">{theme_opts}</select></div></header>
<div class="breadcrumb"><a href="{prefix}/">{_("← Home", lang)}</a> / {safe_name} <a href="{dl_url}" class="btn-dl" title="{_('下载', lang)}">⬇</a></div>
<pre style="background:var(--code-bg);padding:1rem;border-radius:8px;overflow-x:auto;white-space:pre-wrap;font-size:0.875rem;border:1px solid var(--border)">{raw}</pre>
<div class="back-link"><a href="{prefix}/">{_("← 返回首页", lang)}</a></div>"""
    return mk_page(f"{safe_name} — Owlia Nest", body, prefix=prefix, lang=lang)

def render_media(path, prefix="", lang="zh"):
    """Render image/audio files with inline embed."""
    ext = path.suffix.lower()
    from urllib.parse import quote
    safe_url = quote(path.name)
    dl_url = f"{prefix}/download?f={safe_url}&r={path.parent}"
    theme_opts = "".join(f'<option value="{k}">{v["name"]}</option>' for k, v in THEMES.items())
    media_url = f"{prefix}/media?f={path.name}&r={path.parent}"
    safe_name = escape(path.name)

    _audio_mime = {".mp3": "mpeg", ".wav": "wav", ".ogg": "ogg", ".m4a": "mp4", ".opus": "opus"}

    if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"):
        elem = f'<img src="{media_url}" alt="{safe_name}" style="max-width:100%;height:auto;border-radius:6px;display:block">'
    elif ext in _audio_mime:
        elem = f'<audio controls preload="auto" style="width:100%;max-width:480px"><source src="{media_url}" type="audio/{_audio_mime[ext]}"></audio>'
    else:
        elem = f'<p style="color:var(--muted)">{_("暂不支持预览此文件类型", lang)}</p>'

    body = f"""<header><div class="header-brand"><img src="{prefix}/icons/logo.png" alt="Owlia Nest" class="logo" width="32" height="32"><h1>Owlia Nest</h1></div>
  <div class="header-right">
    <button class="lang-toggle" onclick="toggleLang()" title="中 | EN">{_("中 | EN", lang)}</button>
    <select class="theme-select" id="themeSelect">{theme_opts}</select></div></header>
<div class="breadcrumb"><a href="{prefix}/">{_("← Home", lang)}</a> / {safe_name} <a href="{dl_url}" class="btn-dl" title="{_('下载', lang)}">⬇</a></div>
<div style="margin:1rem 0">{elem}</div>
<div style="margin-top:0.5rem;color:var(--muted);font-size:0.8rem">{safe_name} · {size_fmt(path.stat().st_size)}</div>
<div class="back-link"><a href="{prefix}/">{_("← 返回首页", lang)}</a></div>"""
    return mk_page(f"{safe_name} — Owlia Nest", body, prefix=prefix, lang=lang)

# ── WSGI/HTTP handler ────────────────────────────────────────────
def create_app(targets=None, prefix=""):
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
    # Wrap in list to allow mutation from nested Handler
    _state = [targets, exclude_dirs, exclude_exts]
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
                files = scan_files(_t, _e, _x)
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
        # Allow requests without Origin (e.g., PWA, direct fetch)
        if not origin:
            return True
        allow = ("http://localhost", "http://127.0.0.1", "http://0.0.0.0",
                 "https://localhost", "https://127.0.0.1", "https://0.0.0.0",
                 "capacitor://localhost", "file://")
        if origin.startswith(allow):
            return True
        # Also allow if Host header is localhost or known local hostname
        host = (headers.get("Host") or "").split(":")[0]
        if host in ("localhost", "127.0.0.1", "0.0.0.0", "bunker", "bunker.local"):
            return True
        return False

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            raw_path = parsed.path
            path = raw_path[len(prefix):] if prefix and raw_path.startswith(prefix) else raw_path
            if not path.startswith("/"):
                path = "/" + path
            q = parse_qs(parsed.query)
            targets, exclude_dirs, exclude_exts = _state
            lang = get_lang(self)

            if path == "/sw.js":
                self._send(_sw_js(prefix), "application/javascript; charset=utf-8")
            elif path.startswith("/icons/") and path[7:] in ICONS:
                mime, data = ICONS[path[7:]]
                self._send(data, mime)
            elif path.startswith("/icons/"):
                # Serve static files from icons dir (easymde, bytemd, etc.)
                fs_path = os.path.join(os.path.dirname(__file__), "icons", path[len("/icons/"):])
                if os.path.isfile(fs_path):
                    ext = os.path.splitext(fs_path)[1].lower()
                    mime_map = {".css": "text/css", ".js": "application/javascript", ".mjs": "application/javascript",
                                ".png": "image/png", ".svg": "image/svg+xml", ".woff2": "font/woff2"}
                    with open(fs_path, "rb") as f:
                        self._send(f.read(), mime_map.get(ext, "application/octet-stream"))
                else:
                    self.send_error(404)
            elif path == "/favicon.ico":
                if "favicon-32.png" in ICONS:
                    mime, data = ICONS["favicon-32.png"]
                    self._send(data, mime)
            elif path == "/manifest.json":
                self._send(_manifest(prefix), "application/json; charset=utf-8")
            elif path == "/api/dirs":
                # Reload from disk to catch external changes
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
                favs = load_favorites(config_path)
                self._send(json.dumps({"favorites": sorted(favs)}), "application/json; charset=utf-8")
            elif path == "/api/cache-status":
                with _cache_lock:
                    payload = {
                        "scanning": bool(_cache.get("scanning")),
                        "last_scan": _cache.get("last_scan") or 0,
                        "count": len(_cache.get("files") or []),
                        "error": _cache.get("error"),
                    }
                self._send(json.dumps(payload), "application/json; charset=utf-8")
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
                payload = browse_dir(dpath, cap=5000)
                # Breadcrumbs: relative parts from monitored root
                root = None
                for t in targets:
                    if _path_is_within(dpath, t):
                        root = t
                        break
                crumbs = []
                if root is not None:
                    rel = dpath.relative_to(root)
                    cur = root
                    crumbs.append({"name": root.name or str(root), "path": str(root)})
                    for part in rel.parts:
                        cur = cur / part
                        crumbs.append({"name": part, "path": str(cur)})
                payload["breadcrumbs"] = crumbs
                payload["path"] = str(dpath)
                self._send(json.dumps(payload), "application/json; charset=utf-8")
            elif path == "/":
                # Reload config from disk to avoid stale state
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
                        self._html(render_md(fpath, prefix, lang, f_rel, f_root_p))
                    elif ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
                                ".mp3", ".wav", ".ogg", ".m4a", ".opus"):
                        self._html(render_media(fpath, prefix, lang))
                    else:
                        self._html(render_txt(fpath, prefix, lang))
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
                    ext = fpath.suffix.lower()
                    mime_map = {
                        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                        ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
                        ".mp3": "audio/mpeg", ".wav": "audio/wav",
                        ".ogg": "audio/ogg", ".m4a": "audio/mp4", ".opus": "audio/opus",
                    }
                    mime = mime_map.get(ext, "application/octet-stream")
                    self._send(fpath.read_bytes(), mime)
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
                    # Use specific MIME for binary files; text files use octet-stream
                    # to avoid Caddy/proxy interfering with text/* responses
                    mime_map = {
                        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                        ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
                        ".mp3": "audio/mpeg", ".wav": "audio/wav",
                        ".ogg": "audio/ogg", ".m4a": "audio/mp4", ".opus": "audio/opus",
                    }
                    mime = mime_map.get(ext, "application/octet-stream")
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
            if path.startswith("/api/") and path not in ("/api/version", "/api/dirs"):
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
                favs = load_favorites(config_path)
                if fpath in favs:
                    favs.discard(fpath)
                    action = "removed"
                else:
                    favs.add(fpath)
                    action = "added"
                save_favorites(favs, config_path)
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
                if data.get("token") != "owlia-upgrade-2026":
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
                        # Restart in-place: replace this process with upgraded code
                        # Also try launchd/systemd as fallback
                        subprocess.Popen(
                            ["bash", "-c", "sleep 0.5; launchctl stop com.owlia.nest 2>/dev/null; kill $(lsof -ti :8788) 2>/dev/null; true"],
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

        def _send(self, content, ct):
            body = content.encode("utf-8") if isinstance(content, str) else content
            self.send_response(200)
            self.send_header("Content-Type", ct)
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)

        def _html(self, content):
            self._send(content, "text/html; charset=utf-8")

        def log_message(self, fmt, *args):
            pass

    return Handler


def serve(host="127.0.0.1", port=8788, prefix="", targets=None):
    """Start the HTTP server."""
    from http.server import ThreadingHTTPServer
    if targets is None:
        targets = load_config()  # returns (dirs, excludes, exclude_exts)
    prefix = prefix.rstrip("/")

    Handler = create_app(targets, prefix)
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"🦉 Owlia Nest → http://{host}:{port}{prefix}/")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Done")
        httpd.shutdown()
