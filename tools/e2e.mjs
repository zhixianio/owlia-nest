#!/usr/bin/env node
// e2e.mjs — browser end-to-end regression for owlia-nest.
// Drives headless Chrome over CDP (zero npm deps, Node >= 22) through real
// user flows: search, browse, bookmarks (file+folder), edit/save, theme,
// language, auth. Run tools/e2e_serve.py first (or let run_e2e.sh do it).
//
// Usage: node tools/e2e.mjs <fixtureRoot> [--shot-dir /tmp/owlia-e2e]
// Exits 0 if every step passes and zero console/page errors were seen.

import { spawn } from "node:child_process";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const BASE = "http://127.0.0.1:18800/docs";
const AUTH_BASE = "http://127.0.0.1:18801";
const fixtureRoot = process.argv[2];
if (!fixtureRoot) { console.error("usage: node tools/e2e.mjs <fixtureRoot>"); process.exit(2); }
const shotIdx = process.argv.indexOf("--shot-dir");
const SHOT_DIR = shotIdx >= 0 ? process.argv[shotIdx + 1] : "/tmp/owlia-e2e";
mkdirSync(SHOT_DIR, { recursive: true });
const PORT = 9223;
const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let chromeProc = null, userDir = null;
async function ensureChrome() {
  try { await fetch(`http://127.0.0.1:${PORT}/json/version`); return; } catch {}
  userDir = mkdtempSync(join(tmpdir(), "owlia-e2e-chrome-"));
  chromeProc = spawn(CHROME, [
    "--headless=new", `--remote-debugging-port=${PORT}`, `--user-data-dir=${userDir}`,
    "--no-first-run", "--no-default-browser-check", "--disable-gpu",
    "--disable-extensions", "--window-size=1280,1200", "about:blank",
  ], { stdio: "ignore" });
  for (let i = 0; i < 100; i++) {
    try { await fetch(`http://127.0.0.1:${PORT}/json/version`); return; } catch { await sleep(100); }
  }
  throw new Error("Chrome did not come up");
}

class CDP {
  constructor(ws) { this.ws = ws; this.id = 0; this.pending = new Map(); this.handlers = []; }
  static async connect(port) {
    const v = await (await fetch(`http://127.0.0.1:${port}/json/version`)).json();
    const ws = new WebSocket(v.webSocketDebuggerUrl);
    await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
    const cdp = new CDP(ws);
    ws.onmessage = (m) => {
      const msg = JSON.parse(m.data);
      if (msg.id && cdp.pending.has(msg.id)) {
        const { res, rej } = cdp.pending.get(msg.id); cdp.pending.delete(msg.id);
        msg.error ? rej(new Error(msg.error.message)) : res(msg.result);
      } else if (msg.method) { for (const h of cdp.handlers) h(msg); }
    };
    return cdp;
  }
  send(method, params = {}, sessionId) {
    const id = ++this.id;
    return new Promise((res, rej) => {
      this.pending.set(id, { res, rej });
      this.ws.send(JSON.stringify({ id, method, params, sessionId }));
    });
  }
  on(fn) { this.handlers.push(fn); }
}

// ---- harness ----------------------------------------------------------------
const results = [];
const consoleErrors = [];
const pageErrors = [];
const httpErrors = [];
let muteErrors = false;  // auth step deliberately triggers 401s
let S, cdp, sessionId, targetId;

async function ev(expr) {
  const { result, exceptionDetails } = await S("Runtime.evaluate",
    { expression: expr, returnByValue: true, awaitPromise: true });
  if (exceptionDetails) throw new Error("eval failed: " + (exceptionDetails.exception?.description || exceptionDetails.text) + "\n  in: " + expr.slice(0, 120));
  return result.value;
}
async function nav(url) {
  const loaded = new Promise((res) => {
    cdp.on((m) => { if (m.sessionId === sessionId && m.method === "Page.loadEventFired") res(); });
  });
  await S("Page.navigate", { url });
  await Promise.race([loaded, sleep(10000)]);
  await sleep(400);
}
async function waitFor(expr, timeout = 6000, label = expr) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeout) {
    try { if (await ev(expr)) return true; } catch {}
    await sleep(150);
  }
  throw new Error("timeout waiting for: " + label);
}
async function click(sel) {
  const ok = await ev(`(()=>{const el=document.querySelector(${JSON.stringify(sel)});if(el)el.click();return !!el})()`);
  if (!ok) throw new Error("click target not found: " + sel);
  await sleep(250);
}
async function typeInto(sel, text) {
  const ok = await ev(`(()=>{const el=document.querySelector(${JSON.stringify(sel)});if(!el)return false;` +
    `el.value=${JSON.stringify(text)};el.dispatchEvent(new Event('input',{bubbles:true}));return true})()`);
  if (!ok) throw new Error("type target not found: " + sel);
}
async function shot(name) {
  try {
    const s = await S("Page.captureScreenshot", { format: "png" });
    writeFileSync(join(SHOT_DIR, name + ".png"), Buffer.from(s.data, "base64"));
  } catch {}
}
async function step(name, fn) {
  try { await fn(); results.push({ name, ok: true }); console.error("  ✅ " + name); }
  catch (e) {
    results.push({ name, ok: false, error: String(e.message || e) });
    console.error("  ❌ " + name + " — " + (e.message || e));
    await shot("FAIL-" + name.replace(/\W+/g, "_"));
  }
}

// ---- scenarios ----------------------------------------------------------------
async function main() {
  await ensureChrome();
  cdp = await CDP.connect(PORT);
  ({ targetId } = await cdp.send("Target.createTarget", { url: "about:blank" }));
  ({ sessionId } = await cdp.send("Target.attachToTarget", { targetId, flatten: true }));
  S = (m, p) => cdp.send(m, p, sessionId);
  cdp.on((msg) => {
    if (msg.sessionId !== sessionId || muteErrors) return;
    if (msg.method === "Runtime.consoleAPICalled" && msg.params.type === "error")
      consoleErrors.push((msg.params.args || []).map((a) => a.value ?? a.description ?? a.type).join(" "));
    if (msg.method === "Runtime.exceptionThrown")
      pageErrors.push(msg.params.exceptionDetails?.exception?.description || "exception");
    if (msg.method === "Log.entryAdded" && msg.params.entry.level === "error") {
      // The sanitizer fixture leaves <img src=x> (handler stripped) → expected broken image
      if (!msg.params.entry.url || !msg.params.entry.url.endsWith("/docs/x"))
        consoleErrors.push("[log] " + msg.params.entry.text);
    }
    if (msg.method === "Network.responseReceived" && msg.params.response.status >= 400) {
      if (!msg.params.response.url.endsWith("/docs/x"))
        httpErrors.push(msg.params.response.status + " " + msg.params.response.url);
    }
  });
  await S("Page.enable"); await S("Runtime.enable"); await S("Log.enable"); await S("Network.enable");

  // 1. Home renders with cards and tabs
  await step("home: cards + tabs render", async () => {
    await nav(BASE + "/");
    await waitFor(`document.querySelectorAll('.file-card').length >= 5`, 8000, "file cards");
    if (!(await ev(`document.querySelectorAll('.tabs-bar button').length >= 7`))) throw new Error("tabs missing");
    if (!(await ev(`!!document.querySelector('.version-tag')`))) throw new Error("version tag missing");
    await shot("01-home");
  });

  // 2. Deep file (depth 3, unicode dir) visible on home scan
  await step("home: deep unicode-path file scanned", async () => {
    await waitFor(`[...document.querySelectorAll('.file-card .file-name a')].some(a=>a.textContent==='deep-note.md')`,
      8000, "deep-note.md card");
  });

  // 3. Markdown sanitization: fence sample survives, live onerror doesn't
  await step("view md: sanitized render + fence highlighted", async () => {
    const href = await ev(`[...document.querySelectorAll('.file-card .file-name a')].find(a=>a.textContent==='README.md').href`);
    await nav(href);
    await waitFor(`!!document.querySelector('#mdView h1')`, 6000, "md h1");
    if ((await ev(`document.querySelector('#mdView h1').textContent`)) !== "Hello E2E") throw new Error("h1 wrong");
    if (!(await ev(`document.querySelectorAll('#mdView .highlight span[class]').length > 0`))) throw new Error("pygments token missing");
    if (await ev(`!!document.querySelector('#mdView img[onerror]')`)) throw new Error("onerror survived sanitizer!");
    await shot("02-view-md");
  });

  // 4. Edit md → save → in-place refresh → persists across reload
  await step("edit md: EasyMDE save round-trip", async () => {
    await click("#btnEdit");
    await waitFor(`!!document.querySelector('.CodeMirror') && !!window._easyMDE`, 6000, "EasyMDE up");
    await ev(`_easyMDE.value('# Changed by e2e\\n\\nnew body\\n'); true`);
    await click("#btnSave");
    await waitFor(`document.querySelector('#mdView h1') && document.querySelector('#mdView h1').textContent==='Changed by e2e'`,
      6000, "in-place refresh");
    await nav(await ev("location.href"));
    await waitFor(`document.querySelector('#mdView h1') && document.querySelector('#mdView h1').textContent==='Changed by e2e'`,
      6000, "persisted after reload");
    await shot("03-md-saved");
  });

  // 5. Special-char filename: link works end-to-end
  await step("view md: special-char filename opens", async () => {
    await nav(BASE + "/");
    await waitFor(`document.querySelectorAll('.file-card').length >= 5`, 8000, "cards back");
    const href = await ev(`([...document.querySelectorAll('.file-card .file-name a')].find(a=>a.textContent.includes("rd's"))||{}).href || ''`);
    if (!href) throw new Error("special-char card missing");
    await nav(href);
    await waitFor(`document.querySelector('#mdView h1') && document.querySelector('#mdView h1').textContent==='Special chars survive'`,
      6000, "special-char doc rendered");
  });

  // 6. Plain editor for code files
  await step("edit py: plain textarea save round-trip", async () => {
    await nav(BASE + `/view?f=script.py&r=${encodeURIComponent(fixtureRoot)}`);
    await waitFor(`!!document.querySelector('#mdView .highlight')`, 6000, "pygments view");
    await click("#btnEdit");
    await waitFor(`document.querySelector('#mdTextarea').classList.contains('plain-editor')`, 4000, "plain editor");
    await ev(`(()=>{const t=document.querySelector('#mdTextarea');t.value='def changed():\\n    return 1\\n';return true})()`);
    await click("#btnSave");
    await waitFor(`(document.querySelector('#mdView').textContent||'').includes('changed')`, 6000, "py saved");
    await shot("04-py-saved");
  });

  // 7. Server-side search finds deep file; clearing restores tabs
  await step("search: server-side hits deep file", async () => {
    await nav(BASE + "/");
    await waitFor(`document.querySelectorAll('.file-card').length >= 5`, 8000, "cards");
    await typeInto("#searchInput", "deep");
    await waitFor(`(()=>{const p=document.getElementById('searchResults');return p&&p.style.display!=='none'&&p.textContent.includes('deep-note.md')})()`,
      6000, "search results");
    await shot("05-search");
    await typeInto("#searchInput", "");
    await waitFor(`document.getElementById('searchResults').style.display==='none'`, 4000, "results hidden");
  });

  // 8. Browse: navigate into unicode dir, star the FOLDER
  await step("browse: navigate + star folder", async () => {
    await click('.tabs-bar button[data-tab="browse"]');
    await waitFor(`document.querySelectorAll('[data-panel="browse"] .browse-item').length >= 1`, 6000, "browse roots");
    await click('[data-panel="browse"] [data-browse-path]');
    await waitFor(`(document.getElementById('browseList').textContent||'').includes('深层')`, 6000, "dir listing");
    const starSel = `#browseList .browse-item .btn-star`;
    await waitFor(`!!document.querySelector(${JSON.stringify(starSel)})`, 4000, "folder star button");
    await ev(`(()=>{const rows=[...document.querySelectorAll('#browseList .browse-item')];` +
      `const row=rows.find(r=>r.textContent.includes('深层'));row.querySelector('.btn-star').click();return true})()`);
    await waitFor(`[...document.querySelectorAll('#browseList .btn-star')].some(s=>s.textContent==='⭐')`, 6000, "star filled");
    await shot("06-browse-star");
  });

  // 9. Fav tab: folder bookmark renders server-side and opens in browse
  await step("fav: folder bookmark renders + opens browse", async () => {
    await click('.tabs-bar button[data-tab="fav"]');
    await waitFor(`(()=>{const p=document.querySelector('[data-panel="fav"]');return p&&p.style.display!=='none'&&p.textContent.includes('深层')})()`,
      6000, "fav entry");
    await shot("07-fav-tab");
    await ev(`(()=>{const a=[...document.querySelectorAll('[data-panel="fav"] a[data-browse-path]')].find(x=>x.textContent==='深层');a.click();return true})()`);
    await waitFor(`(()=>{const p=document.querySelector('[data-panel="browse"]');return p&&p.style.display!=='none'&&(document.getElementById('browseBreadcrumbs').textContent||'').includes('深层')})()`,
      6000, "browse opened at folder");
    await shot("08-fav-to-browse");
  });

  // 10. Theme switching applies CSS vars
  await step("theme: dracula applies", async () => {
    await ev(`(()=>{const s=document.getElementById('themeSelect');s.value='dracula';s.dispatchEvent(new Event('change'));return true})()`);
    await waitFor(`getComputedStyle(document.body).backgroundColor==='rgb(40, 42, 54)'`, 4000, "dracula bg");
    await ev(`localStorage.removeItem('owlia-theme')`);
  });

  // 11. Language toggle flips zh <-> en (headless Chrome starts as en via Accept-Language)
  await step("i18n: toggle flips language", async () => {
    const before = await ev(`document.documentElement.lang`);
    const expected = before === "en" ? "zh-Hans" : "en";
    await click(".lang-toggle");
    await sleep(800);
    await waitFor(`document.documentElement.lang===${JSON.stringify(expected)}`, 6000,
      `lang attr ${before} → ${expected}`);
    const label = expected === "en" ? "Browse" : "浏览";
    await waitFor(`[...document.querySelectorAll('.tabs-bar button')].some(b=>b.textContent.includes(${JSON.stringify(label)}))`,
      4000, "tab label translated");
    await shot("09-lang-toggled");
  });

  // 12. Auth server: 401 without token, ?token= logs in, cookie persists
  await step("auth: 401 → token login → cookie persists", async () => {
    muteErrors = true;  // the first nav 401s by design
    await nav(AUTH_BASE + "/");
    const denied = await ev(`document.body.textContent.includes('401') || document.title.includes('401')`);
    if (!denied) throw new Error("expected 401 page");
    await nav(AUTH_BASE + "/?token=e2e-token");
    await waitFor(`!!document.querySelector('.tabs-bar')`, 6000, "home after token");
    await nav(AUTH_BASE + "/");  // no token in URL — cookie must carry it
    await waitFor(`!!document.querySelector('.tabs-bar')`, 6000, "cookie session");
    await shot("10-auth");
    muteErrors = false;
  });

  // ---- report ----
  const failed = results.filter((r) => !r.ok);
  // SW registration in headless http can warn; only count real app errors
  const errs = [...consoleErrors, ...pageErrors];
  const summary = {
    passed: results.length - failed.length,
    failed: failed.length,
    steps: results,
    consoleErrors: errs.slice(0, 20),
    httpErrors: httpErrors.slice(0, 20),
    screenshots: SHOT_DIR,
  };
  console.log(JSON.stringify(summary, null, 2));
  await S("Target.closeTarget", { targetId }).catch(() => {});
  cdp.ws.close();
  if (chromeProc) { try { chromeProc.kill("SIGTERM"); } catch {} }
  if (userDir) { try { rmSync(userDir, { recursive: true, force: true }); } catch {} }
  process.exit(failed.length || errs.length ? 1 : 0);
}

main().catch((e) => { console.error("e2e harness failed:", e); process.exit(1); });
