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

## Known fragility
`render_md()` builds the editor HTML/JS/CSS via Python `%`-formatting (note the
`%%` escapes). Adding any `%` or changing the arg count breaks page rendering with
`TypeError: not all arguments converted during string formatting`. Prefer moving
editor front-end into static files under `src/owlia_nest/icons/` over growing the
`%`-template.
