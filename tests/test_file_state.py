"""Remembered file state (file_state.py) and the extras refresh that uses it:
a repeated update must not re-hash or re-download unchanged files, and must
fall back to the full check whenever the file or the CDN object changed."""
import hashlib, os, sys, tempfile, time, unittest
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app
import file_state as FS


def _touch_later(p: Path) -> None:
    st = p.stat()
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))


class FileStateUnit(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.store = self.root / "_state" / "fs.json"
        self.f = self.root / "game" / "extras" / "manual.pdf"
        self.f.parent.mkdir(parents=True)
        self.f.write_bytes(b"manual v1")

    def tearDown(self):
        self._tmp.cleanup()

    def test_md5_remembered_until_file_changes(self):
        s = FS.FileState(self.store, self.root)
        self.assertIsNone(s.md5(self.f))
        s.put(self.f, "ABC")
        s.save()
        s2 = FS.FileState(self.store, self.root)           # survives a restart
        self.assertEqual(s2.md5(self.f), "abc")
        _touch_later(self.f)                               # same size, new mtime
        self.assertIsNone(s2.md5(self.f))
        s2.put(self.f, "abc")
        self.f.write_bytes(b"manual v2 longer")            # different size
        self.assertIsNone(s2.md5(self.f))

    def test_remote_signature_must_match_and_have_a_validator(self):
        s = FS.FileState(self.store, self.root)
        sig = {"etag": '"e1"', "last_modified": "", "length": str(self.f.stat().st_size), "name": "m.pdf"}
        s.put(self.f, "abc", sig)
        self.assertTrue(s.remote_unchanged(self.f, dict(sig)))
        self.assertFalse(s.remote_unchanged(self.f, {**sig, "etag": '"e2"'}))
        self.assertFalse(s.remote_unchanged(self.f, {**sig, "length": "999"}))
        self.assertFalse(s.remote_unchanged(self.f, None))
        no_validator = {"etag": "", "last_modified": "", "length": sig["length"], "name": "m.pdf"}
        s.put(self.f, "abc", no_validator)
        self.assertFalse(s.remote_unchanged(self.f, no_validator))

    def test_outside_root_is_never_cached(self):
        with tempfile.TemporaryDirectory() as other:
            p = Path(other) / "x.bin"
            p.write_bytes(b"x")
            s = FS.FileState(self.store, self.root)
            s.put(p, "abc")
            self.assertIsNone(s.md5(p))

    def test_forget_missing_and_corrupt_store(self):
        s = FS.FileState(self.store, self.root)
        s.put(self.f, "abc")
        self.f.unlink()
        self.assertEqual(s.forget_missing(self.root / "game"), 1)
        s.save()
        self.store.write_text("{not json", encoding="utf-8")
        self.assertIsNone(FS.FileState(self.store, self.root).md5(self.f))


class ExtrasRefresh(unittest.TestCase):
    PATCH = ("BASE", "get_settings", "scan_games", "get_download_manifest", "_access_token_box",
             "_resolve_downlink", "_remote_md5", "_head_signature", "_fetch_to_ram",
             "_md5_path", "_send_js", "log")

    def setUp(self):
        self._orig = {k: getattr(app, k) for k in self.PATCH}
        self._tmp = tempfile.TemporaryDirectory()
        app.BASE = Path(self._tmp.name) / "inst"
        self.folder = app.BASE / "alpha" / "extras"
        self.folder.mkdir(parents=True)
        self.remote = {"manual.pdf": b"PDF-1", "soundtrack.zip": b"ZIP-1" * 10}
        for n, b in self.remote.items():
            (self.folder / n).write_bytes(b)
        self.etags = {n: f'"{n}-1"' for n in self.remote}
        self.checksummed = {"soundtrack.zip"}
        self.settings = {"extras_subdir": True, "update_langs": ["en"]}
        self.ram, self.hashed = [], []
        rows = [{"key": f"extra:{n}", "category": "extra", "name": n,
                 "parts": [{"size": len(b), "downlink": f"dl://{n}"}]} for n, b in self.remote.items()]
        game = {"id": "1", "slug": "alpha", "game_key": "alpha", "title": "Alpha", "product": {"id": 1}}

        app.get_settings = lambda: {**app.DEFAULT_SETTINGS, **self.settings}
        app.scan_games = lambda: [game]
        app.get_download_manifest = lambda gid: {"ok": True, "installers": [], "dlcs": [],
                                                 "language_packs": [], "extras": rows}
        app._access_token_box = lambda: {"access": "T", "refresh": "R", "tokens": {}}
        app._resolve_downlink = lambda dl, box: {
            "downlink": "https://cdn.example/x/" + dl[5:],
            "checksum": ("chk://" + dl[5:]) if dl[5:] in self.checksummed else None}
        app._remote_md5 = lambda url: hashlib.md5(self.remote[url[6:]]).hexdigest()
        app._head_signature = lambda url: {"etag": self.etags[url.rsplit("/", 1)[1]], "last_modified": "",
                                           "length": str(len(self.remote[url.rsplit("/", 1)[1]])),
                                           "name": url.rsplit("/", 1)[1]}

        def ram(url, hub=None, sid=None, name=""):
            n = url.rsplit("/", 1)[1]
            self.ram.append(n)
            return self.remote[n]
        app._fetch_to_ram = ram
        orig_md5 = self._orig["_md5_path"]

        def md5_path(p):
            self.hashed.append(Path(p).name)
            return orig_md5(p)
        app._md5_path = md5_path
        app._send_js = lambda d: None
        app.log = lambda m: None
        app._cancel.clear()

    def tearDown(self):
        for k, v in self._orig.items():
            setattr(app, k, v)
        self._tmp.cleanup()

    def run_update(self):
        self.ram.clear()
        self.hashed.clear()
        self.assertTrue(app._update_worker("1", extras_only=True))

    def test_second_run_downloads_and_hashes_nothing(self):
        self.run_update()
        self.assertEqual(self.ram, ["manual.pdf"])          # first run: full RAM compare
        self.run_update()
        self.assertEqual((self.ram, self.hashed), ([], []))

    def test_changed_cdn_object_is_fetched_and_replaced(self):
        self.run_update()
        self.remote["manual.pdf"] = b"PDF-2-new"
        self.etags["manual.pdf"] = '"manual.pdf-2"'
        self.run_update()
        self.assertEqual(self.ram, ["manual.pdf"])
        self.assertEqual((self.folder / "manual.pdf").read_bytes(), b"PDF-2-new")

    def test_locally_modified_file_is_rechecked(self):
        self.run_update()
        # touched files (same bytes, new mtime) lose their remembered state
        _touch_later(self.folder / "soundtrack.zip")
        _touch_later(self.folder / "manual.pdf")
        self.run_update()
        self.assertIn("soundtrack.zip", self.hashed)           # re-hashed, still identical
        self.assertEqual(self.ram, ["manual.pdf"])             # re-fetched, still identical
        self.run_update()
        self.assertEqual((self.ram, self.hashed), ([], []))    # remembered again

    def test_deep_verify_rechecks_everything(self):
        self.run_update()
        self.settings["deep_verify"] = True
        self.run_update()
        self.assertEqual(self.ram, ["manual.pdf"])
        self.assertIn("soundtrack.zip", self.hashed)


if __name__ == "__main__":
    unittest.main()
