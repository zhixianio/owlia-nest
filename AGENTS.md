# AGENTS.md — owlia-nest

## Dev on the MBP, not over SSH to bunker
This repo is now developed locally on the MacBook. **Do not** debug UI by editing
on bunker and cur/git-syncing — that's blind and slow for a JS editor.

## UI work MUST use the visual loop (see `tools/README.md`)
The editor is **EasyMDE** (client-side JS over CodeMirror). `curl` cannot show its
rendered state. Before claiming an editor change works, verify it with the
browser tool:

```bash
./.venv/bin/python tools/dev_serve.py            # local server on :8788
node tools/browser_check.mjs "<view-url>" --click "#btnEdit" --selector ".CodeMirror" --shot /tmp/shot.png
```

Read the JSON it returns: `verdict.editorRendered` must be `true`, and
`consoleErrors`/`pageErrors` must be empty. If `heightPx<=40` the editor collapsed;
if `backgroundColor` is white the theme didn't apply; a `pageError` from `easymde.js`
means the `new EasyMDE()` call threw.

## Architecture (since 0.3.0)
Front-end lives in static files under `src/owlia_nest/static/` (`app.css`,
`app.js`, `editor.js`, `editor.css`), served via the `/static/` route. Pages get
config through a single `window.OWLIA` JSON blob; the editor reads
`#owliaEditorCfg` + `#mdRawData` JSON blocks. Do NOT inline new JS/CSS into
Python templates — add to the static files instead. Run tests with
`.venv/bin/python -m unittest discover tests`.
