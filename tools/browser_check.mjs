#!/usr/bin/env node
// browser_check.mjs — render a URL in the host's Chrome (headless) and report
// the *runtime* state an agent otherwise can't see: computed styles, console
// errors, and a screenshot. Zero npm deps — drives Chrome over the DevTools
// Protocol using Node's built-in global `fetch` + `WebSocket` (Node >= 22).
//
// Why this exists: a JS-initialized widget (EasyMDE/CodeMirror) renders in the
// browser, so `curl`'d HTML can't show a collapsed height / white background /
// empty editor. This tool surfaces those as text + an image so iteration on the
// owlia-nest editor stops being a blind guess-and-check loop.
//
// Usage:
//   node tools/browser_check.mjs <url> [options]
// Options:
//   --selector <css>   element to probe (default ".CodeMirror")
//   --click <css>      click this selector after load (e.g. the Edit button), then re-probe
//   --wait <ms>        extra settle time after load / click (default 1500)
//   --shot <path>      screenshot output (default /tmp/pi-shot.png)
//   --port <n>         Chrome remote-debugging port (default 9222)
//   --keep             reuse an already-running debug Chrome on <port> (don't launch/kill)
//
// Output: a single JSON object on stdout (signals + screenshot path). Exit 0 on
// success, non-zero on navigation/timeout failure.

import { spawn } from "node:child_process";
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const argv = process.argv.slice(2);
const url = argv.find((a) => !a.startsWith("--"));
if (!url) {
  console.error("usage: node browser_check.mjs <url> [--selector .CodeMirror] [--click <css>] [--wait 1500] [--shot out.png] [--port 9222] [--keep]");
  process.exit(2);
}
const opt = (n, d) => { const i = argv.indexOf(n); return i >= 0 ? argv[i + 1] : d; };
const has = (n) => argv.includes(n);
const selector = opt("--selector", ".CodeMirror");
const clickSel = opt("--click", null);
const waitMs = parseInt(opt("--wait", "1500"), 10);
const shotPath = opt("--shot", join(tmpdir(), "pi-shot.png"));
const port = parseInt(opt("--port", "9222"), 10);
const keep = has("--keep");
const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---- launch (or reuse) a debug Chrome -------------------------------------
let chromeProc = null;
let userDir = null;
async function ensureChrome() {
  // already up?
  try { await fetch(`http://127.0.0.1:${port}/json/version`); return; } catch {}
  if (keep) throw new Error(`--keep set but no Chrome listening on :${port}`);
  userDir = mkdtempSync(join(tmpdir(), "pi-chrome-"));
  chromeProc = spawn(CHROME, [
    "--headless=new", `--remote-debugging-port=${port}`, `--user-data-dir=${userDir}`,
    "--no-first-run", "--no-default-browser-check", "--disable-gpu",
    "--disable-extensions", "--window-size=1280,1400", "about:blank",
  ], { stdio: "ignore", detached: false });
  for (let i = 0; i < 100; i++) {
    try { await fetch(`http://127.0.0.1:${port}/json/version`); return; } catch { await sleep(100); }
  }
  throw new Error("Chrome DevTools endpoint did not come up");
}

// ---- minimal CDP client over one browser websocket (flattened sessions) ----
class CDP {
  constructor(ws) { this.ws = ws; this.id = 0; this.pending = new Map(); this.events = []; this.handlers = []; }
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
      } else if (msg.method) {
        cdp.events.push(msg);
        for (const h of cdp.handlers) h(msg);
      }
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

async function main() {
  await ensureChrome();
  const cdp = await CDP.connect(port);

  // new tab + attach (flatten => use sessionId on subsequent calls)
  const { targetId } = await cdp.send("Target.createTarget", { url: "about:blank" });
  const { sessionId } = await cdp.send("Target.attachToTarget", { targetId, flatten: true });
  const S = (m, p) => cdp.send(m, p, sessionId);

  // collect console + page errors
  const consoleErrors = [];
  const pageErrors = [];
  cdp.on((msg) => {
    if (msg.sessionId !== sessionId) return;
    if (msg.method === "Runtime.consoleAPICalled" && (msg.params.type === "error" || msg.params.type === "warning")) {
      consoleErrors.push(`[${msg.params.type}] ` + (msg.params.args || []).map((a) => a.value ?? a.description ?? a.type).join(" "));
    }
    if (msg.method === "Runtime.exceptionThrown") {
      pageErrors.push(msg.params.exceptionDetails?.exception?.description || msg.params.exceptionDetails?.text || "exception");
    }
    if (msg.method === "Log.entryAdded" && msg.params.entry.level === "error") {
      consoleErrors.push("[log] " + msg.params.entry.text);
    }
  });
  await S("Page.enable"); await S("Runtime.enable"); await S("Log.enable");

  // navigate + wait for load
  const loaded = new Promise((res) => {
    const off = (msg) => { if (msg.sessionId === sessionId && msg.method === "Page.loadEventFired") res(); };
    cdp.on(off);
  });
  await S("Page.navigate", { url });
  await Promise.race([loaded, sleep(15000)]);
  await sleep(waitMs); // let JS widgets initialize

  if (clickSel) {
    await S("Runtime.evaluate", { expression: `(() => { const el = document.querySelector(${JSON.stringify(clickSel)}); if (el) el.click(); return !!el; })()` });
    await sleep(waitMs);
  }

  // probe the target element's *runtime* state
  const probeExpr = `(() => {
    const sel = ${JSON.stringify(selector)};
    const out = { url: location.href, title: document.title,
      easymdeContainer: !!document.querySelector('.EasyMDEContainer'),
      codeMirror: !!document.querySelector('.CodeMirror') };
    const el = document.querySelector(sel);
    if (el) {
      const cs = getComputedStyle(el), r = el.getBoundingClientRect();
      out.target = { selector: sel, found: true,
        heightPx: Math.round(r.height), widthPx: Math.round(r.width),
        visible: r.height > 1 && r.width > 1,
        backgroundColor: cs.backgroundColor, color: cs.color,
        textLength: (el.innerText || '').trim().length };
    } else { out.target = { selector: sel, found: false }; }
    return out;
  })()`;
  const { result } = await S("Runtime.evaluate", { expression: probeExpr, returnByValue: true });
  const signals = result.value || {};

  // screenshot
  try {
    const shot = await S("Page.captureScreenshot", { format: "png" });
    writeFileSync(shotPath, Buffer.from(shot.data, "base64"));
    signals.screenshot = shotPath;
  } catch (e) { signals.screenshot = null; signals.screenshotError = String(e.message); }

  signals.consoleErrors = consoleErrors.slice(0, 20);
  signals.pageErrors = pageErrors.slice(0, 20);

  // simple verdicts so the agent gets an unambiguous read
  const t = signals.target || {};
  signals.verdict = {
    editorRendered: !!(signals.codeMirror && t.found && t.visible),
    suspiciousHeight: t.found && t.heightPx <= 40,       // "one-line" collapse
    looksEmpty: t.found && t.textLength === 0,
    hasErrors: consoleErrors.length > 0 || pageErrors.length > 0,
  };

  console.log(JSON.stringify(signals, null, 2));

  await S("Target.closeTarget", { targetId }).catch(() => {});
  cdp.ws.close();
  if (chromeProc && !keep) { try { chromeProc.kill("SIGTERM"); } catch {} }
  if (userDir && !keep) { try { rmSync(userDir, { recursive: true, force: true }); } catch {} }
}

main().catch((e) => { console.error("browser_check failed:", e.message); process.exit(1); });
