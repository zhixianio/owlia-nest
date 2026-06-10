"""Unit + endpoint tests. Run: .venv/bin/python -m unittest discover tests -v"""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from owlia_nest.server import (  # noqa: E402
    EXTENSIONS, VALID_EXTS, MEDIA_EXTS,
    _sanitize_html, _ver_tuple, classify, icon_for, mime_for, fr_query,
    load_config, save_config, load_favorites, save_favorites, toggle_favorite,
    scan_files, create_app,
)


class TestVersionCompare(unittest.TestCase):
    def test_ordering(self):
        self.assertLess(_ver_tuple("0.2.1"), _ver_tuple("0.2.2"))
        self.assertGreater(_ver_tuple("0.3.0"), _ver_tuple("0.2.9"))
        self.assertEqual(_ver_tuple("v1.2"), (1, 2, 0, 0))

    def test_local_newer_is_not_update(self):
        # dev machine ahead of GitHub must not flag an update
        self.assertFalse(_ver_tuple("0.2.9") > _ver_tuple("0.3.0"))


class TestSanitize(unittest.TestCase):
    def test_strips_script_and_handlers(self):
        html = '<p><script>evil()</script><img src=x onerror="evil()"></p>'
        out = _sanitize_html(html)
        self.assertNotIn("<script", out)
        self.assertNotIn("onerror", out)

    def test_keeps_escaped_code_samples(self):
        html = "<pre><code>&lt;img src=x onerror=alert(1)&gt;</code></pre>"
        self.assertEqual(_sanitize_html(html), html)

    def test_neutralizes_javascript_urls(self):
        out = _sanitize_html('<a href="javascript:alert(1)">x</a>')
        self.assertNotIn("javascript:", out)

    def test_removes_iframes(self):
        out = _sanitize_html('<iframe src="//evil"></iframe><p>ok</p>')
        self.assertNotIn("iframe", out)
        self.assertIn("<p>ok</p>", out)


class TestRegistry(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(classify({"name": "a.md"}), "doc")
        self.assertEqual(classify({"name": "a.py"}), "code")
        self.assertEqual(classify({"name": "a.json"}), "config")
        self.assertEqual(classify({"name": "a.png"}), "media")
        self.assertEqual(classify({"name": "a.unknown"}), "other")

    def test_registry_shape(self):
        for ext, entry in EXTENSIONS.items():
            self.assertEqual(len(entry), 3, ext)
        self.assertIn(".md", VALID_EXTS)
        self.assertIn(".mp3", MEDIA_EXTS)
        self.assertNotIn(".md", MEDIA_EXTS)

    def test_mime(self):
        self.assertEqual(mime_for("x.mp3"), "audio/mpeg")
        self.assertEqual(mime_for("x.weird"), "application/octet-stream")

    def test_icon_fallbacks(self):
        self.assertEqual(icon_for({"name": "x.py"}), "🐍")
        self.assertEqual(icon_for({"name": "x", "is_dir": True}), "📁")


class TestFrQuery(unittest.TestCase):
    def test_encodes_specials(self):
        q = fr_query("we & rd's.md", "/tmp/a b")
        self.assertNotIn("&r=/tmp/a b", q)
        self.assertIn("we%20%26%20rd%27s.md", q)


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.cp = Path(tempfile.mkdtemp()) / "dirs.json"

    def test_round_trip_preserves_favorites(self):
        save_favorites({"/a/b"}, self.cp)
        save_config([Path("/tmp")], self.cp, ["x"], [".log"])
        self.assertEqual(load_favorites(self.cp), {"/a/b"})
        dirs, ex_d, ex_e = load_config(self.cp)
        self.assertEqual(ex_d, ["x"])
        self.assertEqual(ex_e, [".log"])

    def test_toggle(self):
        a1, favs = toggle_favorite("/x", self.cp)
        self.assertEqual((a1, favs), ("added", {"/x"}))
        a2, favs = toggle_favorite("/x", self.cp)
        self.assertEqual((a2, favs), ("removed", set()))

    def test_concurrent_toggles_dont_lose_updates(self):
        paths = [f"/p/{i}" for i in range(20)]
        threads = [threading.Thread(target=toggle_favorite, args=(p, self.cp)) for p in paths]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(load_favorites(self.cp), set(paths))


class TestScan(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "a.md").write_text("x")
        (self.root / "skipme").mkdir()
        (self.root / "skipme" / "b.md").write_text("x")
        deep = self.root / "d1" / "d2" / "d3"
        deep.mkdir(parents=True)
        (deep / "deep.md").write_text("x")
        (self.root / "noise.xyz").write_text("x")
        (self.root / "c.log").write_text("x")

    def names(self, **kw):
        return {f["name"] for f in scan_files([self.root], **kw)}

    def test_depth(self):
        self.assertIn("deep.md", self.names(max_depth=4))
        self.assertNotIn("deep.md", self.names(max_depth=1))

    def test_exclusions_and_validity(self):
        ns = self.names(exclude_dirs=["skipme"], exclude_exts=[".md"])
        self.assertEqual(ns, set())  # .md excluded, .xyz/.log never valid
        self.assertNotIn("b.md", self.names(exclude_dirs=["skipme"]))


class TestEndpoints(unittest.TestCase):
    """Live-server tests: ephemeral targets + token auth."""
    TOKEN = "test-token"
    PORT = 18799

    @classmethod
    def setUpClass(cls):
        from http.server import ThreadingHTTPServer
        cls.root = Path(tempfile.mkdtemp())
        (cls.root / "hello.md").write_text("# hi\n")
        (cls.root / "sub").mkdir()
        (cls.root / "sub" / "note.txt").write_text("note\n")
        cls.config = cls.root / "config.json"
        Handler = create_app(([cls.root], [], []), "", ephemeral=True, auth_token=cls.TOKEN,
                             config_path=cls.config)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", cls.PORT), Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.PORT}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def get(self, path, authed=True, method="GET", body=None):
        headers = {"Cookie": f"owlia_auth={self.TOKEN}"} if authed else {}
        if body is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_auth_required(self):
        code, _ = self.get("/", authed=False)
        self.assertEqual(code, 401)
        code, _ = self.get("/api/dirs", authed=False)
        self.assertEqual(code, 401)

    def test_home_and_view(self):
        code, body = self.get("/")
        self.assertEqual(code, 200)
        self.assertIn(b"Owlia Nest", body)
        code, body = self.get(f"/view?f=hello.md&r={self.root}")
        self.assertEqual(code, 200)
        self.assertIn(b"mdView", body)

    def test_view_traversal_blocked(self):
        code, _ = self.get(f"/view?f=../../etc/hosts&r={self.root}")
        self.assertEqual(code, 403)
        code, _ = self.get("/view?f=hosts&r=/etc")
        self.assertEqual(code, 403)

    def test_static_traversal_blocked(self):
        code, _ = self.get("/static/../server.py")
        self.assertIn(code, (403, 404))

    def test_search(self):
        self.get("/")  # trigger scan
        time.sleep(0.5)
        code, body = self.get("/api/search?q=hello")
        self.assertEqual(code, 200)
        data = json.loads(body)
        self.assertEqual([r["name"] for r in data["results"]], ["hello.md"])

    def test_favorite_dir_and_file(self):
        sub = str(self.root / "sub")
        code, body = self.get("/api/favorites/toggle", method="POST", body={"path": sub})
        self.assertEqual(json.loads(body)["action"], "added")
        code, body = self.get("/api/favorites")
        entry = [e for e in json.loads(body)["favorites"] if e["path"] == sub][0]
        self.assertTrue(entry["is_dir"])
        self.get("/api/favorites/toggle", method="POST", body={"path": sub})

    def test_favorite_outside_targets_rejected(self):
        code, body = self.get("/api/favorites/toggle", method="POST", body={"path": "/etc"})
        self.assertFalse(json.loads(body)["ok"])

    def test_post_origin_csrf_blocked(self):
        headers = {"Cookie": f"owlia_auth={self.TOKEN}",
                   "Content-Type": "application/json",
                   "Origin": "https://evil.example"}
        req = urllib.request.Request(self.base + "/api/refresh",
                                     data=b"{}", headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req) as r:
                code = r.status
        except urllib.error.HTTPError as e:
            code = e.code
        self.assertEqual(code, 403)
        # Same-origin POST (Origin matches Host) is allowed
        headers["Origin"] = self.base
        req = urllib.request.Request(self.base + "/api/refresh",
                                     data=b"{}", headers=headers, method="POST")
        with urllib.request.urlopen(req) as r:
            self.assertEqual(r.status, 200)

    def test_save_endpoint(self):
        code, body = self.get("/api/save", method="POST",
                              body={"f": "hello.md", "r": str(self.root), "content": "# changed\n"})
        self.assertTrue(json.loads(body)["ok"])
        self.assertEqual((self.root / "hello.md").read_text(), "# changed\n")
        # outside root rejected
        code, _ = self.get("/api/save", method="POST",
                           body={"f": "../x.md", "r": str(self.root), "content": "x"})
        self.assertEqual(code, 403)


if __name__ == "__main__":
    unittest.main()
