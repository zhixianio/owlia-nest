# Local dev + visual debug loop

Tools for developing owlia-nest **locally on the MBP** with a real browser
preview — so UI work (especially the EasyMDE editor) is never debugged blind or
round-tripped through git→bunker again.

## Why
owlia-nest's editor is EasyMDE (a client-side JS widget wrapping CodeMirror).
Its failure modes — collapsed one-line height, white background, empty content,
init exceptions — are *runtime* DOM/CSS states. `curl`'d HTML can't show them.
You need a browser that renders the JS and reports what actually happened.

## One-time setup
```bash
python3 -m venv .venv
./.venv/bin/pip install markdown pygments
```

## The loop
```bash
# 1. serve a sample docs dir locally (bypasses ~/.config; never touches prod)
./.venv/bin/python tools/dev_serve.py            # serves ./.devdocs on :8788 /docs
#    (or pass dirs: ./.venv/bin/python tools/dev_serve.py ~/some/docs)

# 2. edit src/owlia_nest/server.py ... then re-run dev_serve (Ctrl-C + restart)

# 3. SEE the rendered editor — render, click Edit, probe CodeMirror, screenshot
node tools/browser_check.mjs \
  "http://127.0.0.1:8788/docs/view?f=HELLO.md&r=$(python3 -c 'import urllib.parse,os;print(urllib.parse.quote(os.path.abspath(".devdocs")))')" \
  --click "#btnEdit" --selector ".CodeMirror" --shot /tmp/owlia-editor.png
```

`browser_check.mjs` prints JSON you can act on without seeing the image:
- `target.heightPx` / `backgroundColor` / `textLength` — catches "one-line",
  "white bg", "empty"
- `consoleErrors` / `pageErrors` — catches EasyMDE init exceptions (with stack)
- `verdict.editorRendered` — the single boolean that says "did it actually work"
- `screenshot` — PNG path for your own eyes

It drives the installed Google Chrome over the DevTools Protocol with **zero npm
deps** (Node's built-in `fetch` + `WebSocket`, Node ≥ 22). Launches a throwaway
headless instance on a temp profile; pass `--keep` to reuse one you started with
`--remote-debugging-port=9222`.

## Deploy to bunker only after it works locally
Once the editor renders correctly here, push and pull/restart on bunker. The
git→bunker round-trip is for *shipping*, not for *debugging*.
