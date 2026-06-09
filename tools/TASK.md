# TASK — finish the owlia-nest editor "save" work (local, verified)

You are working LOCALLY on this MacBook in /Users/zhixian/Codes/owlia-nest.
Read AGENTS.md and tools/README.md first — they define the required dev loop.

Hard rule: do NOT edit on bunker or use git/curl to debug. Develop locally and
VERIFY every UI change in a real browser with tools/browser_check.mjs before
claiming anything works. curl cannot see the EasyMDE editor; the browser tool can.
(browser_check runs Chrome headless — no window will appear; read its JSON.)

GOAL:
1. FIRST fix the editor so it renders. Clicking Edit throws
   `TypeError: e.replace is not a function` from new EasyMDE() in toggleEdit
   (non-string initialValue — investigate _mdRaw / the mdRawData JSON in render_md).
2. THEN: Save button saves WITHOUT leaving edit mode; Ctrl+S / Cmd+S saves and
   preventDefault()s the browser's native save dialog.

DEV LOOP (repeat until green):
  a. pkill -f dev_serve.py; ./.venv/bin/python tools/dev_serve.py &
  b. edit src/owlia_nest/server.py
  c. node tools/browser_check.mjs \
       "http://127.0.0.1:8788/docs/view?f=HELLO.md&r=$(python3 -c 'import urllib.parse,os;print(urllib.parse.quote(os.path.abspath(".devdocs")))')" \
       --click "#btnEdit" --selector ".CodeMirror" --shot /tmp/shot.png
  d. NOT done until: verdict.editorRendered==true; consoleErrors==[] and
     pageErrors==[]; target.heightPx is a few hundred px (not <=40);
     backgroundColor is the dark theme (not white); save works (button + Cmd+S),
     stays in edit mode, file on disk changes, no browser save dialog.

CONSTRAINTS: keep changes minimal, in src/owlia_nest/server.py. Watch render_md's
%-formatting (%% escapes) — wrong % count throws "not all arguments converted".
If it fights you, move editor JS/CSS into a static file under src/owlia_nest/icons/.
Show the final browser_check JSON + screenshot path as proof.

DEPLOY (only after green locally): commit, push, then on bunker pull + restart,
confirm once with browser_check against the bunker URL.
