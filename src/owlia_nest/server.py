"""OWlia Docs server — Markdown renderer with themes, PWA, categorization."""

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import markdown
from markdown.extensions import codehilite, fenced_code, tables, toc

MD_EXTENSIONS = [
    fenced_code.FencedCodeExtension(),
    codehilite.CodeHiliteExtension(guess_lang=False, css_class="highlight"),
    tables.TableExtension(),
    toc.TocExtension(permalink=True),
]

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
    return f"""const CACHE = 'owlia-nest-v2-{prefix}';
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
.breadcrumb { font-size: 0.875rem; color: var(--muted); margin-bottom: 1rem; }
.breadcrumb a { color: var(--accent); text-decoration: none; }
.breadcrumb a:hover { text-decoration: underline; }
.file-card { display: flex; align-items: baseline; gap: 0.75rem; padding: 0.6rem 0.5rem; border-bottom: 1px solid var(--border); border-radius: 6px; transition: background 0.15s; }
.file-card:hover { background: var(--card-bg); }
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
.btn-tiny { font-size: 0.7rem; padding: 0.25rem 0.5rem; border: 1px solid var(--border); border-radius: 5px; background: var(--card-bg); cursor: pointer; touch-action: manipulation; }
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

PAGE_TPL = """\
<!doctype html>
<html lang="zh-Hans">
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
    }}
  }});
  /* Settings */
  loadDirs();
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
  t.textContent = '🔄 新版本可用，点击更新';
  t.onclick = function(){{
    if (_swReg && _swReg.waiting) {{ _swReg.waiting.postMessage('skip-waiting'); }}
    t.textContent = '更新中…';
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
  if (btn) {{ btn.disabled = true; btn.textContent = '⏳ 升级中…'; }}
  api('POST','{api_base}/api/upgrade').then(function(r){{
    if (r.ok) {{
      if (status) {{ status.textContent = '✅ 升级完成，等待服务重启…'; status.style.color = '#22c55e'; }}
      if (status2) {{ status2.textContent = '✅ 升级完成，等待服务重启…'; status2.style.color = '#22c55e'; }}
      // Poll for server to come back
      var attempts = 0;
      function poll() {{
        attempts++;
        fetch('{api_base}/').then(function(res){{
          if (res.ok) {{
            var el = status || status2;
            if (el) {{ el.innerHTML = '✅ 服务已重启 <a href="#" onclick="location.reload()" style="color:var(--accent);text-decoration:underline">点击刷新</a>'; }}
          }} else if (attempts < 30) {{ setTimeout(poll, 2000); }}
        }}).catch(function(){{
          if (attempts < 30) setTimeout(poll, 2000);
        }});
      }}
      setTimeout(poll, 3000);
    }} else {{
      if (status) {{ status.textContent = '❌ 升级失败: ' + (r.error || r.output || '未知错误'); status.style.color = '#ef4444'; }}
      if (status2) {{ status2.textContent = '❌ 升级失败: ' + (r.error || r.output || '未知错误'); status2.style.color = '#ef4444'; }}
      if (btn) {{ btn.disabled = false; btn.textContent = '⚡ 一键升级'; }}
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
      b.innerHTML = '🆕 <strong>v'+info.latest+'</strong> 已发布（当前 v'+info.local+'）<br><button onclick="upgradeNow()" class="btn-add" style="margin:0.25rem 0">⚡ 一键升级</button><br><small id="upgradeStatus2" style="color:var(--muted)"></small><br><button onclick="this.parentNode.remove()" style="margin-top:0.25rem;padding:0.15rem 0.5rem;border:1px solid var(--border);border-radius:6px;background:none;color:var(--muted);cursor:pointer;font-size:0.75rem">忽略</button>';
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
function api(method,url,body){{ return fetch(url,{{method:method,headers:{{'Content-Type':'application/json'}},body:body?JSON.stringify(body):null}}).then(function(r){{return r.json()}}); }}
function loadDirs(){{
  api('GET','{api_base}/api/dirs').then(function(data){{
    var dirs = Array.isArray(data) ? data : data.dirs || [];
    var excludeDirs = data.exclude_dirs || [];
    var excludeExts = data.exclude_exts || [];
    var el=document.getElementById('dirList');
    if(el){{ el.innerHTML=dirs.map(function(d){{ return '<div class="dir-item"><span class="dir-path">'+d+'</span><button class="dir-remove" data-dir="'+encodeURIComponent(d)+'" title="移除">×</button></div>'; }}).join('')||'<span style="color:var(--muted);font-size:0.8rem">暂无监控目录</span>'; }}
    var exEl=document.getElementById('excludeDirList');
    if(exEl){{ exEl.innerHTML=excludeDirs.map(function(d){{ return '<span class="exclude-tag">📁 '+d+' <button class="dir-remove" data-exdir="'+encodeURIComponent(d)+'" title="移除排除">×</button></span>'; }}).join('')||'<span style="color:var(--muted);font-size:0.75rem">无</span>'; }}
    var extEl=document.getElementById('excludeExtList');
    if(extEl){{ extEl.innerHTML=excludeExts.map(function(e){{ return '<span class="exclude-tag">'+e+' <button class="dir-remove" data-exext="'+encodeURIComponent(e)+'" title="移除排除">×</button></span>'; }}).join('')||'<span style="color:var(--muted);font-size:0.75rem">无</span>'; }}
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
  if(!confirm('移除 '+d+' ？'))return;
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
    else alert('添加失败: ' + (r.error || '未知错误'));
  }});
}}
function quickExcludeDir(name,btn){{
  if (btn.textContent === '↩ 撤销') {{
    api('POST','{api_base}/api/remove-exclude-dir',{{dir:name}}).then(function(r){{
      if(r.ok){{ toast('已恢复目录: '+name); setTimeout(function(){{location.reload()}},800); }}
      else alert(r.error||'操作失败');
    }}).catch(function(e){{ alert('网络错误: '+e); }});
  }} else {{
    toast('将排除目录: '+name+'\\n（相同目录下的其他文件也会一并隐藏）');
    api('POST','{api_base}/api/exclude-dir',{{dir:name}}).then(function(r){{
      if(r.ok){{ btn.textContent='↩ 撤销'; btn.title='撤销排除'; toast('✅ 已排除目录: '+name); }}
      else alert(r.error||'排除失败');
    }}).catch(function(e){{ alert('网络错误: '+e); }});
  }}
}}
function quickExcludeExt(ext,btn){{
  if (btn.textContent === '↩ 撤销') {{
    api('POST','{api_base}/api/remove-exclude-ext',{{ext:ext}}).then(function(r){{
      if(r.ok){{ toast('已恢复类型: '+ext); setTimeout(function(){{location.reload()}},800); }}
      else alert(r.error||'操作失败');
    }}).catch(function(e){{ alert('网络错误: '+e); }});
  }} else {{
    toast('将排除类型: '+ext+'\\n（所有同扩展名文件都会被隐藏）');
    api('POST','{api_base}/api/exclude-ext',{{ext:ext}}).then(function(r){{
      if(r.ok){{ btn.textContent='↩ 撤销'; btn.title='撤销排除'; toast('✅ 已排除类型: '+ext); }}
      else alert(r.error||'排除失败');
    }}).catch(function(e){{ alert('网络错误: '+e); }});
  }}
}}
function toast(msg){{
  var id='_toast'; var e=document.getElementById(id); if(e)e.remove();
  e=document.createElement('div'); e.id=id;
  e.style.cssText='position:fixed;bottom:2rem;left:50%;transform:translateX(-50%);background:var(--fg);color:var(--bg);padding:0.6rem 1.2rem;border-radius:8px;font-size:0.85rem;z-index:9999;white-space:pre-line;text-align:center;box-shadow:0 4px 16px rgba(0,0,0,0.3);transition:opacity 0.3s';
  e.textContent=msg; document.body.appendChild(e);
  setTimeout(function(){{ e.style.opacity='0'; setTimeout(function(){{if(e.parentNode)e.remove()}},300); }},2500);
}}
// Delegated click handler for exclude buttons
document.addEventListener('click',function(e){{
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
</script>
</body>
</html>
"""

CATEGORIES = {
    "recent": ("🕐", "最近更新"), "doc": ("📄", "文档"),
    "code": ("💻", "代码"), "config": ("⚙️", "配置"), "media": ("🎬", "媒体"),
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
    data = {"dirs": [str(d) for d in dirs]}
    existing = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text())
        except Exception:
            pass
    data["exclude_dirs"] = exclude_dirs if exclude_dirs is not None else existing.get("exclude_dirs", [])
    data["exclude_exts"] = exclude_exts if exclude_exts is not None else existing.get("exclude_exts", [])
    path.write_text(json.dumps(data, indent=2))
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
            for fpath in sorted(target.rglob("*")):
                if fpath.is_file() and not fpath.name.startswith("."):
                    if skip_parts & set(fpath.parts):
                        continue
                    # Check if file is inside an excluded full path
                    if any(skip_path in fpath.parents for skip_path in skip_paths):
                        continue
                    ext = fpath.suffix.lower()
                    if ext in exclude_ext_set:
                        continue
                    if ext in valid_ext:
                        files.append(scan_file(fpath, target))
    files.sort(key=lambda f: f["mtime"], reverse=True)
    return files

# ── Utilities ─────────────────────────────────────────────────────
def size_fmt(n):
    if n < 1024: return f"{n}B"
    if n < 1024 * 1024: return f"{n / 1024:.0f}KB"
    return f"{n / (1024*1024):.0f}MB"

def time_ago(mtime):
    diff = time.time() - mtime
    if diff < 60: return "刚才"
    if diff < 3600: return f"{int(diff / 60)}分钟前"
    if diff < 86400: return f"{int(diff / 3600)}小时前"
    if diff < 604800: return f"{int(diff / 86400)}天前"
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
def mk_page(title, body, head_extra="", default_theme="github-dark", prefix=""):
    theme_css = THEMES[default_theme]["css"].strip()
    theme_json = json.dumps({k: theme_dict(k) for k in THEMES})
    theme_js = f"var THEMES = {theme_json};"
    return PAGE_TPL.format(
        title=title, body=body, head_extra=head_extra,
        __theme_css__=theme_css, __theme_js__=theme_js,
        BASE_CSS=BASE_CSS, default_theme=default_theme,
        api_base=prefix,
    )

def file_card(f, href):
    dname = os.path.dirname(f["path"])
    fpath = f["path"]
    ext = f["name"].rsplit(".", 1)[-1].lower() if "." in f["name"] else ""
    return (
        f'<div class="file-card" data-cat="{classify(f)}">'
        f'<span class="file-icon">{icon_for(f)}</span>'
        f'<span class="file-name"><a href="{href}?f={f["rel_path"]}&r={f["root"]}">{f["name"]}</a>'
        f'<br><span class="file-path">{fpath}</span></span>'
        f'<span class="file-date">{time_ago(f["mtime"])}</span>'
        f'<span class="file-size">{size_fmt(f["size"])}</span>'
        f'<span class="file-actions">'
        f'<button class="btn-tiny" data-exclude-dir="{dname}" title="排除此目录">📁⊘</button>'
        + (f'<button class="btn-tiny" data-exclude-ext=".{ext}" title="排除 .{ext}">📎⊘</button>' if ext else '') +
        f'</span></div>'
    )

def render_home(files, prefix=""):
    view_url = prefix + "/view"
    cats = {k: [] for k in CATEGORIES}
    cats["recent"] = [file_card(f, view_url) for f in files[:30]]
    for f in files:
        c = classify(f)
        if c in cats:
            cats[c].append(file_card(f, view_url))

    tabs = '<nav class="tabs-bar" aria-label="Categories">'
    for key, (emoji, label) in CATEGORIES.items():
        active = ' class="tab-active"' if key == "recent" else ""
        cnt = len(cats[key])
        cnt_str = f' <span class="tab-count">{cnt}</span>' if cnt else ""
        tabs += f'<button{active} data-tab="{key}">{emoji} {label}{cnt_str}</button>'
    tabs += '</nav>'

    secs = []
    for key, cards in cats.items():
        hidden = '' if key == "recent" else ' style="display:none"'
        if cards:
            secs.append(f'<section class="tab-panel" data-panel="{key}"{hidden}>{"".join(cards)}</section>')
        else:
            secs.append(f'<section class="tab-panel" data-panel="{key}"{hidden}><p style="color:var(--muted);padding:2rem;text-align:center">暂无内容</p></section>')

    theme_opts = "".join(f'<option value="{k}">{v["name"]}</option>' for k, v in THEMES.items())
    ver = _check_remote_version()
    local_ver = ver["local"]
    has_update = ver.get("has_update")
    latest_ver = ver.get("latest", "")
    version_html = f'<span class="version-tag">v{local_ver}</span>'
    upgrade_banner = ""
    if has_update and latest_ver:
        version_html += f' <span class="version-upgrade" onclick="upgradeNow()">🆕 v{latest_ver}</span>'
        upgrade_banner = f'<div id="upgradeBanner" class="upgrade-banner">🆕 <strong>v{latest_ver}</strong> 已发布（当前 v{local_ver}）<br><button onclick="upgradeNow()" class="btn-add" style="margin:0.25rem 0">⚡ 一键升级</button><br><small id="upgradeStatus" style="color:var(--muted)"></small></div>'
    header = f"""<header>
  <div class="header-brand"><img src="{prefix}/icons/logo.png" alt="Owlia Nest" class="logo" width="32" height="32"><div><h1>Owlia Nest</h1><p>PA 产出文档中心</p></div></div>
  <div class="header-right">
    {version_html}
    <button class="theme-select" id="settingsToggle" title="管理目录" onclick="toggleSettings()">⚙️</button>
    <select class="theme-select" id="themeSelect">{theme_opts}</select>
    <button class="theme-select" onclick="location.reload()" title="刷新">↻</button>
  </div>
</header>
{upgrade_banner}
<div id="settingsPanel" class="settings-panel" style="display:none">
  <div class="settings-title">📂 监控目录</div>
  <div id="dirList" class="dir-list">加载中…</div>
  <div class="add-dir-row">
    <input id="dirInput" type="text" class="dir-input" placeholder="输入目录路径，如 ~/my-project">
    <button class="btn-add" onclick="addDir()">+ 添加</button>
  </div>
  <div class="settings-title" style="margin-top:1rem">🚫 排除子目录</div>
  <div id="excludeDirList" class="exclude-list">加载中…</div>
  <div class="add-dir-row">
    <input id="excludeDirInput" type="text" class="dir-input" placeholder="目录名，如 archive">
    <button class="btn-add" onclick="addExcludeDir()">+ 排除</button>
  </div>
  <div class="settings-title" style="margin-top:1rem">🚫 排除文件类型</div>
  <div id="excludeExtList" class="exclude-list">加载中…</div>
  <div class="add-dir-row">
    <input id="excludeExtInput" type="text" class="dir-input" placeholder="扩展名，如 .json">
    <button class="btn-add" onclick="addExcludeExt()">+ 排除</button>
  </div>
</div>"""

    head_extra = f'<link rel="manifest" href="{prefix}/manifest.json">'
    body = header + tabs + "\n".join(secs)
    return mk_page("Owlia Nest", body, head_extra, prefix=prefix)

def render_md(path, prefix=""):
    raw = path.read_text(encoding="utf-8", errors="replace")
    html = markdown.markdown(raw, extensions=MD_EXTENSIONS)
    theme_opts = "".join(f'<option value="{k}">{v["name"]}</option>' for k, v in THEMES.items())
    body = f"""<header><div class="header-brand"><img src="{prefix}/icons/logo.png" alt="Owlia Nest" class="logo" width="32" height="32"><h1>Owlia Nest</h1></div>
  <div class="header-right"><select class="theme-select" id="themeSelect">{theme_opts}</select></div></header>
<div class="breadcrumb"><a href="{prefix}/">← Home</a> / {path.name}</div>
<div class="markdown-body">{html}</div>
<div class="back-link"><a href="{prefix}/">← 返回首页</a></div>"""
    return mk_page(f"{path.name} — Owlia Nest", body, prefix=prefix)

def render_txt(path, prefix=""):
    raw = path.read_text(encoding="utf-8", errors="replace")
    theme_opts = "".join(f'<option value="{k}">{v["name"]}</option>' for k, v in THEMES.items())
    body = f"""<header><div class="header-brand"><img src="{prefix}/icons/logo.png" alt="Owlia Nest" class="logo" width="32" height="32"><h1>Owlia Nest</h1></div>
  <div class="header-right"><select class="theme-select" id="themeSelect">{theme_opts}</select></div></header>
<div class="breadcrumb"><a href="{prefix}/">← Home</a> / {path.name}</div>
<pre style="background:var(--code-bg);padding:1rem;border-radius:8px;overflow-x:auto;white-space:pre-wrap;font-size:0.875rem;border:1px solid var(--border)">{raw}</pre>
<div class="back-link"><a href="{prefix}/">← 返回首页</a></div>"""
    return mk_page(f"{path.name} — Owlia Nest", body, prefix=prefix)

def render_media(path, prefix=""):
    """Render image/audio files with inline embed."""
    ext = path.suffix.lower()
    theme_opts = "".join(f'<option value="{k}">{v["name"]}</option>' for k, v in THEMES.items())
    media_url = f"{prefix}/media?f={path.name}&r={path.parent}"

    _audio_mime = {".mp3": "mpeg", ".wav": "wav", ".ogg": "ogg", ".m4a": "mp4", ".opus": "opus"}

    if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"):
        elem = f'<img src="{media_url}" alt="{path.name}" style="max-width:100%;height:auto;border-radius:6px;display:block">'
    elif ext in _audio_mime:
        elem = f'<audio controls preload="auto" style="width:100%;max-width:480px"><source src="{media_url}" type="audio/{_audio_mime[ext]}"></audio>'
    else:
        elem = f'<p style="color:var(--muted)">暂不支持预览此文件类型</p>'

    body = f"""<header><div class="header-brand"><img src="{prefix}/icons/logo.png" alt="Owlia Nest" class="logo" width="32" height="32"><h1>Owlia Nest</h1></div>
  <div class="header-right"><select class="theme-select" id="themeSelect">{theme_opts}</select></div></header>
<div class="breadcrumb"><a href="{prefix}/">← Home</a> / {path.name}</div>
<div style="margin:1rem 0">{elem}</div>
<div style="margin-top:0.5rem;color:var(--muted);font-size:0.8rem">{path.name} · {size_fmt(path.stat().st_size)}</div>
<div class="back-link"><a href="{prefix}/">← 返回首页</a></div>"""
    return mk_page(f"{path.name} — Owlia Nest", body, prefix=prefix)

# ── WSGI/HTTP handler ────────────────────────────────────────────
def create_app(targets=None, prefix=""):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import parse_qs, urlparse

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

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            raw_path = parsed.path
            path = raw_path[len(prefix):] if prefix and raw_path.startswith(prefix) else raw_path
            if not path.startswith("/"):
                path = "/" + path
            q = parse_qs(parsed.query)
            targets, exclude_dirs, exclude_exts = _state

            if path == "/sw.js":
                self._send(_sw_js(prefix), "application/javascript; charset=utf-8")
            elif path.startswith("/icons/") and path[7:] in ICONS:
                mime, data = ICONS[path[7:]]
                self._send(data, mime)
            elif path == "/favicon.ico":
                if "favicon-32.png" in ICONS:
                    mime, data = ICONS["favicon-32.png"]
                    self._send(data, mime)
            elif path == "/manifest.json":
                self._send(_manifest(prefix), "application/json; charset=utf-8")
            elif path == "/api/dirs":
                self._send(json.dumps({
                    "dirs": [str(d) for d in targets],
                    "exclude_dirs": exclude_dirs,
                    "exclude_exts": exclude_exts,
                }), "application/json; charset=utf-8")
            elif path == "/api/version":
                info = _check_remote_version()
                self._send(json.dumps(info), "application/json; charset=utf-8")
            elif path == "/":
                files = scan_files(targets, exclude_dirs, exclude_exts)
                self._html(render_home(files, prefix))
            elif path == "/view":
                f_rel = q.get("f", [None])[0]
                f_root = q.get("r", [None])[0]
                if not f_rel or not f_root:
                    self.send_error(404); return
                fpath = Path(f_root) / f_rel
                if fpath.exists() and fpath.is_file():
                    ext = fpath.suffix.lower()
                    if ext == ".md":
                        self._html(render_md(fpath, prefix))
                    elif ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
                                ".mp3", ".wav", ".ogg", ".m4a", ".opus"):
                        self._html(render_media(fpath, prefix))
                    else:
                        self._html(render_txt(fpath, prefix))
                else:
                    self.send_error(404, "File not found")
            elif path == "/media":
                f_rel = q.get("f", [None])[0]
                f_root = q.get("r", [None])[0]
                if not f_rel or not f_root:
                    self.send_error(404); return
                fpath = Path(f_root) / f_rel
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
            else:
                self.send_error(404)

        def do_POST(self):
            parsed = urlparse(self.path)
            raw_path = parsed.path
            path = raw_path[len(prefix):] if prefix and raw_path.startswith(prefix) else raw_path
            if not path.startswith("/"):
                path = "/" + path
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8", errors="replace")
            try:
                data = json.loads(body) if body else {}
            except json.JSONDecodeError:
                data = {}
            targets, exclude_dirs, exclude_exts = _state

            if path == "/api/add-dir":
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
                try:
                    result = subprocess.run(
                        [sys.executable, "-m", "pip", "install", "--upgrade",
                         "git+https://github.com/zhixianio/owlia-nest.git"],
                        capture_output=True, text=True, timeout=60
                    )
                    ok = result.returncode == 0
                    msg = result.stdout.split("\n")[-3:] if ok else result.stderr[-200:]
                    if ok:
                        # Schedule restart in background
                        subprocess.Popen(
                            ["bash", "-c", "sleep 2; launchctl stop com.owlia.nest 2>/dev/null; launchctl kickstart gui/$(id -u)/com.owlia.nest 2>/dev/null; systemctl --user restart owlia-nest 2>/dev/null"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True
                        )
                    self._send(json.dumps({"ok": ok, "output": "\n".join(msg),
                                           "restarting": ok}),
                                "application/json")
                except Exception as e:
                    self._send(json.dumps({"ok": False, "error": str(e)}),
                                "application/json")
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
