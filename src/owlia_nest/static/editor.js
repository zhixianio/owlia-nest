/* Owlia Nest file editor.
 * Config: <script type="application/json" id="owliaEditorCfg">{f, r, prefix, mode, saveLabel}</script>
 *   mode: "md" (EasyMDE, full toolbar) | "txt" (EasyMDE, slim toolbar) | "plain" (textarea, code/config)
 * Raw content: <script type="application/json" id="mdRawData">"..."</script> (JSON string)
 */
'use strict';
var _edCfg = JSON.parse(document.getElementById('owliaEditorCfg').textContent);
var _easyMDE = null;
var _mdRaw = null;

function _rawContent(){
  if (_mdRaw === null) {
    try { _mdRaw = JSON.parse(document.getElementById('mdRawData').textContent); } catch (e) { _mdRaw = ''; }
  }
  return _mdRaw;
}

function toggleEdit(){
  var raw = _rawContent();
  document.getElementById('mdView').style.display = 'none';
  document.getElementById('mdEditor').style.display = '';
  document.getElementById('btnEdit').style.display = 'none';
  document.getElementById('btnSave').style.display = '';
  document.getElementById('btnCancel').style.display = '';
  var ta = document.getElementById('mdTextarea');
  if (_edCfg.mode === 'plain') {
    ta.classList.add('plain-editor');
    ta.value = raw;
    ta.focus();
    return;
  }
  if (!_easyMDE) {
    var opts = {
      element: ta,
      initialValue: raw,
      spellChecker: false,
      status: false,
      autosave: { enabled: false },
      renderingConfig: { codeSyntaxHighlighting: true }
    };
    if (_edCfg.mode === 'txt') {
      opts.toolbar = ["bold", "italic", "|", "unordered-list", "ordered-list", "|", "quote", "code", "|", "preview", "fullscreen", "|", "guide"];
    }
    _easyMDE = new EasyMDE(opts);
  } else {
    _easyMDE.value(raw);
  }
}

function cancelEdit(){
  document.getElementById('mdView').style.display = '';
  document.getElementById('mdEditor').style.display = 'none';
  document.getElementById('btnEdit').style.display = '';
  document.getElementById('btnSave').style.display = 'none';
  document.getElementById('btnCancel').style.display = 'none';
}

function _editorValue(){
  if (_edCfg.mode === 'plain') return document.getElementById('mdTextarea').value;
  return _easyMDE ? _easyMDE.value() : '';
}

function saveEdit(){
  var content = _editorValue();
  var btn = document.getElementById('btnSave');
  btn.disabled = true;
  btn.textContent = '⏳';
  fetch(_edCfg.prefix + '/api/save', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ f: _edCfg.f, r: _edCfg.r, content: content })
  }).then(function(r){ return r.json(); }).then(function(r){
    if (r.ok) {
      _mdRaw = content;
      // Refresh the rendered view in place, stay in edit mode
      var viewUrl = _edCfg.prefix + '/view?f=' + encodeURIComponent(_edCfg.f) + '&r=' + encodeURIComponent(_edCfg.r);
      fetch(viewUrl).then(function(resp){ return resp.text(); }).then(function(html){
        var tmp = document.createElement('div');
        tmp.innerHTML = html;
        var newView = tmp.querySelector('#mdView');
        if (newView) {
          document.getElementById('mdView').innerHTML = newView.innerHTML;
        }
        btn.textContent = '✅ ' + _edCfg.saveLabel;
        setTimeout(function(){ btn.textContent = '💾 ' + _edCfg.saveLabel; }, 1200);
        btn.disabled = false;
      }).catch(function(){
        btn.textContent = _edCfg.saveLabel;
        btn.disabled = false;
      });
    } else {
      alert(r.error || 'Save failed');
      btn.textContent = _edCfg.saveLabel;
      btn.disabled = false;
    }
  }).catch(function(e){
    alert('Network error: ' + e);
    btn.textContent = _edCfg.saveLabel;
    btn.disabled = false;
  });
}

/* Ctrl+S / Cmd+S → save while editing */
document.addEventListener('keydown', function(e){
  if ((e.ctrlKey || e.metaKey) && e.key === 's') {
    var saveBtn = document.getElementById('btnSave');
    if (saveBtn && saveBtn.style.display !== 'none') {
      e.preventDefault();
      saveEdit();
    }
  }
});
