/* Owlia Nest page script. Config injected as window.OWLIA = {prefix, lang, i18n, themes, defaultTheme}. */
'use strict';
var API = OWLIA.prefix;
var __LANG = OWLIA.lang;
var I18N = OWLIA.i18n;
var THEMES = OWLIA.themes;

function _(k){ return I18N[k] || k; }

function escapeHtml(s){
  s = (s === null || s === undefined) ? '' : String(s);
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

function toggleLang(){
  var n = __LANG === 'zh' ? 'en' : 'zh';
  document.cookie = 'lang=' + n + ';path=/;max-age=31536000';
  var u = new URL(location.href);
  u.searchParams.set('lang', n);
  location.href = u.toString();
}

/* ── Theme + tabs ── */
(function(){
  var sel = document.getElementById('themeSelect');
  if (sel) {
    var saved = localStorage.getItem('owlia-theme') || OWLIA.defaultTheme;
    sel.value = saved;
    _apply(saved);
    sel.onchange = function(){ _apply(this.value); localStorage.setItem('owlia-theme', this.value); };
  }
  function _apply(k){
    var t = THEMES[k]; if (!t) return;
    var r = document.documentElement;
    Object.keys(t).forEach(function(v){ r.style.setProperty('--' + v, t[v]); });
    if (sel) sel.value = k;
  }
  var btns = document.querySelectorAll('.tabs-bar button');
  btns.forEach(function(b){
    b.onclick = function(){
      btns.forEach(function(x){ x.classList.remove('tab-active'); });
      b.classList.add('tab-active');
      var key = b.dataset.tab;
      document.querySelectorAll('.tab-panel').forEach(function(p){ p.style.display = 'none'; });
      var el = document.querySelector('[data-panel="' + key + '"]');
      if (el) el.style.display = '';
      if (key === 'browse') initBrowse();
      if (key === 'fav') renderFavTab();
      doSearch();
    };
  });
})();

/* ── Service worker + update toast ── */
var _swReg = null;
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register(API + '/sw.js').then(function(reg){
    _swReg = reg;
    reg.onupdatefound = function(){
      var newWorker = reg.installing;
      if (!newWorker) return;
      newWorker.onstatechange = function(){
        if (newWorker.state === 'installed' && navigator.serviceWorker.controller) {
          showUpdateToast();
        }
      };
    };
    setInterval(function(){ reg.update(); }, 60 * 1000);
  });
  var refreshing = false;
  navigator.serviceWorker.oncontrollerchange = function(){
    if (!refreshing) { refreshing = true; location.reload(); }
  };
}
function showUpdateToast(){
  var t = document.createElement('div');
  t.id = 'updateToast';
  t.style.cssText = 'position:fixed;bottom:1rem;right:1rem;background:var(--accent);color:#fff;padding:0.75rem 1rem;border-radius:8px;font-size:0.875rem;z-index:9999;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,0.3);';
  t.textContent = _('🔄 新版本可用，点击更新');
  t.onclick = function(){
    if (_swReg && _swReg.waiting) { _swReg.waiting.postMessage('skip-waiting'); }
    t.textContent = _('更新中…');
  };
  document.body.appendChild(t);
}

/* ── Upgrade ── */
function showUpgradeCmd(e){
  e.preventDefault();
  var b = document.getElementById('upgradeBanner');
  if (b) b.style.display = b.style.display === 'none' ? '' : 'none';
}
function upgradeNow(){
  var btn = document.querySelector('#upgradeBanner .btn-add');
  var status = document.getElementById('upgradeStatus');
  var status2 = document.getElementById('upgradeStatus2');
  if (btn) { btn.disabled = true; btn.textContent = _('⏳ 升级中…'); }
  api('POST', API + '/api/upgrade', {}).then(function(r){
    if (r.ok) {
      if (status) { status.textContent = _('✅ 升级完成，等待服务重启…'); status.style.color = '#22c55e'; }
      if (status2) { status2.textContent = _('✅ 升级完成，等待服务重启…'); status2.style.color = '#22c55e'; }
      var attempts = 0;
      function poll(){
        attempts++;
        fetch(API + '/').then(function(res){
          if (res.ok) {
            var el = status || status2;
            if (el) { el.innerHTML = _('✅ 服务已重启 ') + '<a href="#" onclick="location.reload()" style="color:var(--accent);text-decoration:underline">' + _('点击刷新') + '</a>'; }
          } else if (attempts < 30) { setTimeout(poll, 2000); }
        }).catch(function(){
          if (attempts < 30) setTimeout(poll, 2000);
        });
      }
      setTimeout(poll, 3000);
    } else {
      if (status) { status.textContent = _('❌ 升级失败: ') + (r.error || r.output || _('未知错误')); status.style.color = '#ef4444'; }
      if (status2) { status2.textContent = _('❌ 升级失败: ') + (r.error || r.output || _('未知错误')); status2.style.color = '#ef4444'; }
      if (btn) { btn.disabled = false; btn.textContent = _('⚡ 一键升级'); }
    }
  });
}
setTimeout(checkVersion, 5000);
setInterval(checkVersion, 30 * 60 * 1000);
function checkVersion(){
  api('GET', API + '/api/version').then(function(info){
    if (info && info.has_update && info.latest) {
      var id = 'upgradeBanner';
      if (document.getElementById(id)) return;
      var b = document.createElement('div');
      b.id = id;
      b.style.cssText = 'position:fixed;bottom:1rem;left:1rem;right:1rem;background:var(--bg);border:2px solid var(--accent);color:var(--fg);padding:0.75rem 1rem;border-radius:8px;font-size:0.875rem;z-index:9998;text-align:center;box-shadow:0 2px 12px rgba(0,0,0,0.2);max-width:500px;margin:0 auto;';
      b.innerHTML = '🆕 <strong>v' + escapeHtml(info.latest) + '</strong> ' + _('已发布（当前 v') + escapeHtml(info.local) + _('）') +
        '<br><button onclick="upgradeNow()" class="btn-add" style="margin:0.25rem 0">' + _('⚡ 一键升级') + '</button>' +
        '<br><small id="upgradeStatus2" style="color:var(--muted)"></small>' +
        '<br><button onclick="this.parentNode.remove()" style="margin-top:0.25rem;padding:0.15rem 0.5rem;border:1px solid var(--border);border-radius:6px;background:none;color:var(--muted);cursor:pointer;font-size:0.75rem">' + _('忽略') + '</button>';
      document.body.appendChild(b);
    }
  });
}

/* ── Settings panel ── */
function toggleSettings(){
  var p = document.getElementById('settingsPanel');
  p.style.display = p.style.display === 'none' ? 'block' : 'none';
  if (p.style.display === 'block') loadDirs();
}
function api(method, url, body){
  return fetch(url, {
    method: method,
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : null
  }).then(function(r){ if (!r.ok) throw new Error(r.status); return r.json(); });
}
function loadDirs(){
  api('GET', API + '/api/dirs').then(function(data){
    var dirs = Array.isArray(data) ? data : data.dirs || [];
    var excludeDirs = data.exclude_dirs || [];
    var excludeExts = data.exclude_exts || [];
    var el = document.getElementById('dirList');
    if (el) {
      el.innerHTML = dirs.map(function(d){
        return '<div class="dir-item"><span class="dir-path">' + escapeHtml(d) + '</span><button class="dir-remove" data-dir="' + encodeURIComponent(d) + '" title="' + _('移除') + '">×</button></div>';
      }).join('') || '<span style="color:var(--muted);font-size:0.8rem">' + _('暂无监控目录') + '</span>';
    }
    var exEl = document.getElementById('excludeDirList');
    if (exEl) {
      exEl.innerHTML = excludeDirs.map(function(d){
        return '<span class="exclude-tag">📁 ' + escapeHtml(d) + ' <button class="dir-remove" data-exdir="' + encodeURIComponent(d) + '" title="' + _('移除排除') + '">×</button></span>';
      }).join('') || '<span style="color:var(--muted);font-size:0.75rem">' + _('无') + '</span>';
    }
    var extEl = document.getElementById('excludeExtList');
    if (extEl) {
      extEl.innerHTML = excludeExts.map(function(e){
        return '<span class="exclude-tag">' + escapeHtml(e) + ' <button class="dir-remove" data-exext="' + encodeURIComponent(e) + '" title="' + _('移除排除') + '">×</button></span>';
      }).join('') || '<span style="color:var(--muted);font-size:0.75rem">' + _('无') + '</span>';
    }
    document.querySelectorAll('.dir-remove[data-dir]').forEach(function(btn){ btn.onclick = function(){ removeDir(decodeURIComponent(this.dataset.dir)); }; });
    document.querySelectorAll('.dir-remove[data-exdir]').forEach(function(btn){ btn.onclick = function(){ removeExcludeDir(decodeURIComponent(this.dataset.exdir)); }; });
    document.querySelectorAll('.dir-remove[data-exext]').forEach(function(btn){ btn.onclick = function(){ removeExcludeExt(decodeURIComponent(this.dataset.exext)); }; });
  });
}
function addDir(){
  var inp = document.getElementById('dirInput');
  if (!inp || !inp.value.trim()) return;
  api('POST', API + '/api/add-dir', { dir: inp.value.trim() }).then(function(r){
    if (r.ok) { inp.value = ''; loadDirs(); setTimeout(function(){ location.reload(); }, 500); }
    else alert(r.error || 'Failed');
  });
}
function removeDir(d){
  d = decodeURIComponent(d);
  if (!confirm(_('移除 ') + d + _(' ？'))) return;
  api('POST', API + '/api/remove-dir', { dir: d }).then(function(r){
    if (r.ok) { loadDirs(); setTimeout(function(){ location.reload(); }, 500); }
    else alert(r.error || 'Failed');
  });
}
function addExcludeDir(){
  var inp = document.getElementById('excludeDirInput');
  if (!inp || !inp.value.trim()) return;
  api('POST', API + '/api/exclude-dir', { dir: inp.value.trim() }).then(function(r){
    if (r.ok) { inp.value = ''; loadDirs(); setTimeout(function(){ location.reload(); }, 500); }
    else alert(r.error || 'Failed');
  });
}
function removeExcludeDir(d){
  d = decodeURIComponent(d);
  api('POST', API + '/api/remove-exclude-dir', { dir: d }).then(function(r){
    if (r.ok) { loadDirs(); setTimeout(function(){ location.reload(); }, 500); }
    else alert(r.error || 'Failed');
  });
}
function addExcludeExt(){
  var inp = document.getElementById('excludeExtInput');
  if (!inp || !inp.value.trim()) return;
  api('POST', API + '/api/exclude-ext', { ext: inp.value.trim() }).then(function(r){
    if (r.ok) { inp.value = ''; loadDirs(); setTimeout(function(){ location.reload(); }, 500); }
    else alert(_('添加失败: ') + (r.error || _('未知错误')));
  });
}
function removeExcludeExt(e){
  e = decodeURIComponent(e);
  api('POST', API + '/api/remove-exclude-ext', { ext: e }).then(function(r){
    if (r.ok) { loadDirs(); setTimeout(function(){ location.reload(); }, 500); }
    else alert(r.error || 'Failed');
  });
}
function quickExcludeDir(name, btn){
  if (btn.textContent === _('↩ 撤销')) {
    api('POST', API + '/api/remove-exclude-dir', { dir: name }).then(function(r){
      if (r.ok) { toast(_('已恢复目录: ') + name); setTimeout(function(){ location.reload(); }, 800); }
      else alert(r.error || _('操作失败'));
    }).catch(function(e){ alert(_('网络错误: ') + e); });
  } else {
    toast(_('将排除目录: ') + name + _('\n（相同目录下的其他文件也会一并隐藏）'));
    api('POST', API + '/api/exclude-dir', { dir: name }).then(function(r){
      if (r.ok) { btn.textContent = _('↩ 撤销'); btn.title = _('↩ 撤销'); toast(_('✅ 已排除目录: ') + name); setTimeout(function(){ location.reload(); }, 1200); }
      else alert(r.error || _('操作失败'));
    }).catch(function(e){ alert(_('网络错误: ') + e); });
  }
}
function quickExcludeExt(ext, btn){
  if (btn.textContent === _('↩ 撤销')) {
    api('POST', API + '/api/remove-exclude-ext', { ext: ext }).then(function(r){
      if (r.ok) { toast(_('已恢复类型: ') + ext); setTimeout(function(){ location.reload(); }, 800); }
      else alert(r.error || _('操作失败'));
    }).catch(function(e){ alert(_('网络错误: ') + e); });
  } else {
    toast(_('将排除类型: ') + ext + _('\n（所有同扩展名文件都会被隐藏）'));
    api('POST', API + '/api/exclude-ext', { ext: ext }).then(function(r){
      if (r.ok) { btn.textContent = _('↩ 撤销'); btn.title = _('↩ 撤销'); toast(_('✅ 已排除类型: ') + ext); setTimeout(function(){ location.reload(); }, 1200); }
      else alert(r.error || _('操作失败'));
    }).catch(function(e){ alert(_('网络错误: ') + e); });
  }
}
function toast(msg){
  var id = '_toast'; var e = document.getElementById(id); if (e) e.remove();
  e = document.createElement('div'); e.id = id;
  e.style.cssText = 'position:fixed;bottom:2rem;left:50%;transform:translateX(-50%);background:var(--fg);color:var(--bg);padding:0.6rem 1.2rem;border-radius:8px;font-size:0.85rem;z-index:9999;white-space:pre-line;text-align:center;box-shadow:0 4px 16px rgba(0,0,0,0.3);transition:opacity 0.3s';
  e.textContent = msg; document.body.appendChild(e);
  setTimeout(function(){ e.style.opacity = '0'; setTimeout(function(){ if (e.parentNode) e.remove(); }, 300); }, 2500);
}

/* ── Favorites ── */
var _favorites = new Set();
function loadFavorites(){
  try {
    var local = localStorage.getItem('owlia-nest-favs');
    if (local) { _favorites = new Set(JSON.parse(local)); }
  } catch (e) {}
  renderStars();
  updateFavCount();
  api('GET', API + '/api/favorites').then(function(data){
    if (data && data.favorites) { _favorites = new Set(data.favorites.map(favPath)); }
    renderStars();
    updateFavCount();
    try { localStorage.setItem('owlia-nest-favs', JSON.stringify(Array.from(_favorites))); } catch (e) {}
  }).catch(function(){});
}
function favPath(entry){ return (typeof entry === 'string') ? entry : entry.path; }
function toggleFav(fpath, starEl){
  var wasFaved = _favorites.has(fpath);
  if (wasFaved) {
    _favorites.delete(fpath); starEl.textContent = '☆'; starEl.classList.remove('faved'); starEl.title = _('收藏');
  } else {
    _favorites.add(fpath); starEl.textContent = '⏳'; starEl.classList.add('faved'); starEl.title = _('取消收藏');
  }
  updateFavCount();
  try { localStorage.setItem('owlia-nest-favs', JSON.stringify(Array.from(_favorites))); } catch (e) {}
  api('POST', API + '/api/favorites/toggle', { path: fpath }).then(function(r){
    if (r && r.ok) { renderStars(); return; }
    throw new Error('api failed');
  }).catch(function(){
    if (wasFaved) { _favorites.add(fpath); } else { _favorites.delete(fpath); }
    renderStars();
    updateFavCount();
    try { localStorage.setItem('owlia-nest-favs', JSON.stringify(Array.from(_favorites))); } catch (e) {}
  });
}
function renderStars(){
  document.querySelectorAll('.btn-star').forEach(function(star){
    var fpath = star.dataset.filepath;
    if (!fpath) return;
    if (_favorites.has(fpath)) {
      star.textContent = '⭐'; star.classList.add('faved'); star.title = _('取消收藏');
    } else {
      star.textContent = '☆'; star.classList.remove('faved'); star.title = _('收藏');
    }
  });
}
function updateFavCount(){
  var btn = document.querySelector('.tabs-bar button[data-tab="fav"]');
  if (btn) { var cnt = btn.querySelector('.tab-count'); if (cnt) cnt.textContent = _favorites.size; }
}
function renderFavTab(){
  var panel = document.querySelector('[data-panel="fav"]');
  if (!panel) return;
  api('GET', API + '/api/favorites').then(function(data){
    var entries = (data && data.favorites) || [];
    if (!entries.length) {
      panel.innerHTML = '<p style="color:var(--muted);padding:2rem;text-align:center">' + _('暂无内容') + '</p>';
      return;
    }
    var html = '';
    entries.forEach(function(en){
      if (typeof en === 'string') { en = { path: en, name: en, exists: true, is_dir: false }; }
      var icon = en.is_dir ? '📁' : (en.icon || '📄');
      var star = '<button class="btn-star faved" data-filepath="' + escapeHtml(en.path) + '" title="' + _('取消收藏') + '" onclick="event.preventDefault();event.stopPropagation();toggleFav(this.dataset.filepath,this)">⭐</button>';
      var label;
      if (!en.exists) {
        label = '<span style="color:var(--muted);text-decoration:line-through">' + escapeHtml(en.name) + '</span>';
      } else if (en.is_dir) {
        label = '<a href="#" data-browse-path="' + escapeHtml(en.path) + '">' + escapeHtml(en.name) + '</a>';
      } else if (en.view_url) {
        label = '<a href="' + escapeHtml(en.view_url) + '">' + escapeHtml(en.name) + '</a>';
      } else {
        label = escapeHtml(en.name);
      }
      html += '<div class="file-card">' +
        '<span class="file-icon">' + icon + '</span>' + star +
        '<span class="file-name">' + label +
        '<br><span class="file-path">' + escapeHtml(en.path) + '</span></span>' +
        (en.mtime_ago ? '<span class="file-date">' + escapeHtml(en.mtime_ago) + '</span>' : '') +
        '</div>';
    });
    panel.innerHTML = html;
  }).catch(function(){
    panel.innerHTML = '<p style="color:var(--muted);padding:2rem;text-align:center">' + _('暂无内容') + '</p>';
  });
}

/* ── Browse tab ── */
var _browseState = { path: null, inited: false, dirs: [] };
function initBrowse(){
  if (_browseState.inited) return;
  _browseState.inited = true;
  api('GET', API + '/api/dirs').then(function(info){
    var dirs = (info && info.dirs) ? info.dirs : [];
    if (dirs.length === 0) return;
    _browseState.dirs = dirs;
    renderBrowseRoot(dirs);
  }).catch(function(){});
}
function browseStar(p){
  return '<button class="btn-star" data-filepath="' + escapeHtml(p) + '" title="' + _('收藏') + '" onclick="event.preventDefault();event.stopPropagation();toggleFav(this.dataset.filepath,this)">☆</button>';
}
function renderBrowseRoot(dirs){
  var bcEl = document.getElementById('browseBreadcrumbs');
  var listEl = document.getElementById('browseList');
  if (!bcEl || !listEl) return;
  bcEl.innerHTML = '<span style="color:var(--muted)">📂 ' + _('监控目录') + '</span>';
  var h = '';
  for (var j = 0; j < dirs.length; j++) {
    var d = dirs[j];
    h += '<div class="browse-item" data-browse-path="' + escapeHtml(d) + '">📁 ' + escapeHtml(d) + '</div>';
  }
  listEl.innerHTML = h;
  doSearch();
}
function loadBrowse(p){
  if (!p) return;
  _browseState.path = p;
  var url = API + '/api/browse?path=' + encodeURIComponent(p);
  fetch(url).then(function(r){ return r.json(); }).then(function(data){
    renderBrowse(data);
  }).catch(function(e){
    var el = document.getElementById('browseList');
    if (el) el.innerHTML = '<p style="color:var(--muted)">' + escapeHtml(String(e)) + '</p>';
  });
}
function renderBrowse(data){
  var bcEl = document.getElementById('browseBreadcrumbs');
  var listEl = document.getElementById('browseList');
  if (!bcEl || !listEl) return;
  if (!data || !data.ok) {
    bcEl.innerHTML = '';
    listEl.innerHTML = '<p style="color:var(--muted)">' + escapeHtml((data && data.error) || 'Failed') + '</p>';
    return;
  }
  var bcs = data.breadcrumbs || [];
  var bcHtml = '<a href="#" class="browse-item" data-browse-root="1">📂 ' + _('监控目录') + '</a>';
  for (var i = 0; i < bcs.length; i++) {
    var c = bcs[i];
    bcHtml += ' / <a href="#" class="browse-item" data-browse-path="' + escapeHtml(c.path) + '">' + escapeHtml(c.name) + '</a>';
  }
  bcEl.innerHTML = bcHtml;
  var ds = data.dirs || [];
  var fs = data.files || [];
  var h = '';
  for (var j = 0; j < ds.length; j++) {
    var d = ds[j];
    h += '<div class="browse-item"><span data-browse-path="' + escapeHtml(d.path) + '">📁 ' + escapeHtml(d.name) + '</span> ' + browseStar(d.path) + '</div>';
  }
  for (var k = 0; k < fs.length; k++) {
    var f = fs[k];
    var fRel = f.rel_path || f.name;
    var fRoot = data.root || data.path;
    var href = API + '/view?f=' + encodeURIComponent(fRel) + '&r=' + encodeURIComponent(fRoot);
    h += '<div class="browse-item">📄 <a href="' + href + '">' + escapeHtml(f.name) + '</a> ' + browseStar(f.path) + '</div>';
  }
  listEl.innerHTML = h || '<p style="color:var(--muted)">' + _('暂无内容') + '</p>';
  renderStars();
  doSearch();
}

/* ── Search (server-side across full scan, falls back to DOM filter) ── */
var _searchTimer = null;
var _searchSeq = 0;
function doSearch(){
  var inp = document.getElementById('searchInput');
  var q = (inp && inp.value) ? inp.value.trim() : '';
  var resultsPanel = document.getElementById('searchResults');
  if (!resultsPanel) { domFilter(q.toLowerCase()); return; }
  if (!q) {
    resultsPanel.style.display = 'none';
    document.querySelectorAll('.tab-panel').forEach(function(p){ p.style.display = 'none'; });
    var activeBtn = document.querySelector('.tabs-bar button.tab-active');
    var key = activeBtn ? activeBtn.getAttribute('data-tab') : 'recent';
    var el = document.querySelector('[data-panel="' + key + '"]');
    if (el) el.style.display = '';
    return;
  }
  clearTimeout(_searchTimer);
  _searchTimer = setTimeout(function(){
    var seq = ++_searchSeq;
    api('GET', API + '/api/search?q=' + encodeURIComponent(q)).then(function(data){
      if (seq !== _searchSeq) return;
      var inpNow = document.getElementById('searchInput');
      if (!inpNow || inpNow.value.trim() !== q) return;
      renderSearchResults(data && data.results ? data.results : []);
    }).catch(function(){ domFilter(q.toLowerCase()); });
  }, 200);
}
function renderSearchResults(results){
  var panel = document.getElementById('searchResults');
  if (!panel) return;
  document.querySelectorAll('.tab-panel').forEach(function(p){ p.style.display = 'none'; });
  panel.style.display = '';
  if (!results.length) {
    panel.innerHTML = '<p style="color:var(--muted);padding:2rem;text-align:center">' + _('暂无内容') + '</p>';
    return;
  }
  var h = '';
  results.forEach(function(f){
    var href = API + '/view?f=' + encodeURIComponent(f.rel_path) + '&r=' + encodeURIComponent(f.root);
    h += '<div class="file-card">' +
      '<span class="file-icon">' + (f.icon || '📄') + '</span>' +
      '<button class="btn-star" data-filepath="' + escapeHtml(f.path) + '" title="' + _('收藏') + '" onclick="event.preventDefault();event.stopPropagation();toggleFav(this.dataset.filepath,this)">☆</button>' +
      '<span class="file-name"><a href="' + href + '" data-filepath="' + escapeHtml(f.path) + '">' + escapeHtml(f.name) + '</a>' +
      '<br><span class="file-path">' + escapeHtml(f.path) + '</span></span>' +
      '<span class="file-date">' + escapeHtml(f.mtime_ago || '') + '</span>' +
      '</div>';
  });
  panel.innerHTML = h;
  renderStars();
}
function domFilter(q){
  var activeBtn = document.querySelector('.tabs-bar button.tab-active');
  var key = activeBtn ? activeBtn.getAttribute('data-tab') : 'recent';
  var panel = document.querySelector('[data-panel="' + key + '"]');
  if (!panel) return;
  var items = panel.querySelectorAll('.file-card, .browse-item');
  for (var i = 0; i < items.length; i++) {
    var it = items[i];
    if (!q) { it.style.display = ''; continue; }
    var t = (it.textContent || '').toLowerCase();
    it.style.display = (t.indexOf(q) >= 0) ? '' : 'none';
  }
}

/* ── Delegated clicks (browse nav + quick exclude) ── */
document.addEventListener('click', function(e){
  var r = e.target.closest('[data-browse-root]');
  if (r) { e.preventDefault(); renderBrowseRoot(_browseState.dirs); return; }
  var b = e.target.closest('[data-browse-path]');
  if (b) {
    e.preventDefault();
    // From the fav tab, jump to browse tab first
    var browseBtn = document.querySelector('.tabs-bar button[data-tab="browse"]');
    var panel = document.querySelector('[data-panel="browse"]');
    if (browseBtn && panel && panel.style.display === 'none') browseBtn.click();
    loadBrowse(b.getAttribute('data-browse-path'));
    return;
  }
  var btn = e.target.closest('.btn-tiny');
  if (!btn) return;
  var d = btn.getAttribute('data-exclude-dir');
  if (d) { quickExcludeDir(d, btn); return; }
  var ext = btn.getAttribute('data-exclude-ext');
  if (ext) { quickExcludeExt(ext, btn); return; }
});

/* ── Init ── */
(function(){
  loadDirs();
  loadFavorites();
  var qp = new URLSearchParams(location.search);
  var browseTarget = qp.get('browse');
  if (browseTarget) {
    var browseBtn = document.querySelector('.tabs-bar button[data-tab="browse"]');
    if (browseBtn) browseBtn.click();
    setTimeout(function(){ loadBrowse(browseTarget); }, 100);
  }
})();
