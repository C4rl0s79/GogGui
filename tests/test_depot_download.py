"""Shared depot downloader — content assembly, resume state and per-depot SFC.
Network is replaced by a fake _fetch_chunk / _cs_get_zlib (offline)."""
import os, sys, unittest, tempfile
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app


CHUNKS = {"c1": b"AB", "c2": b"CD", "s1": b"hello world", "s2": b"XYZ-12345"}


class _FakeNet:
    def setUp(self):
        self._orig_fetch = app._fetch_chunk
        self.fetched = []

        def fake_fetch(secure, md5):
            self.fetched.append(md5)
            return CHUNKS[md5]
        app._fetch_chunk = fake_fetch
        app._cancel.clear()

    def tearDown(self):
        app._fetch_chunk = self._orig_fetch


def _plain(path, *md5s):
    return {"path": path, "chunks": [{"compressedMd5": m, "size": len(CHUNKS[m])} for m in md5s]}


def _sfc_file(path, off, size):
    return {"path": path, "sfcRef": {"offset": off, "size": size}}


def _sfc(md5):
    return {"chunks": [{"compressedMd5": md5, "size": len(CHUNKS[md5])}]}


class DownloadFileset(_FakeNet, unittest.TestCase):
    def test_assembles_files_and_sfc(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            plain = [_plain("dir\\a.bin", "c1", "c2"), {"path": "empty.txt", "chunks": []}]
            sfced = [_sfc_file("s\\one.txt", 0, 5), _sfc_file("s\\two.txt", 6, 5)]
            errs = app._download_depot_fileset(plain, sfced, _sfc("s1"), "sec", root, 2,
                                               lambda n: None)
            self.assertEqual(errs, [])
            self.assertEqual((root / "dir/a.bin").read_bytes(), b"ABCD")
            self.assertEqual((root / "empty.txt").read_bytes(), b"")
            self.assertEqual((root / "s/one.txt").read_bytes(), b"hello")
            self.assertEqual((root / "s/two.txt").read_bytes(), b"world")
            self.assertFalse(list(root.glob("__gog_sfc*.tmp")))     # temp cleaned

    def test_persist_only_per_chunked_file(self):
        # Regression (1.4.3): SFC / empty files must NOT rewrite the state file
        # one tiny file at a time (quadratic disk churn).
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            calls, done = [], set()
            plain = [_plain("a.bin", "c1"), {"path": "e.txt", "chunks": []}]
            sfced = [_sfc_file(f"s/{i}.txt", 0, 1) for i in range(50)]
            app._download_depot_fileset(plain, sfced, _sfc("s1"), "sec", root, 2,
                                        lambda n: None, done=done,
                                        persist=lambda: calls.append(1))
            self.assertEqual(len(calls), 1)                  # only a.bin
            self.assertEqual(done, {"a.bin", "e.txt"})       # SFC files not tracked

    def test_resume_skips_done_files(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "a.bin").write_bytes(b"AB")
            app._download_depot_fileset([_plain("a.bin", "c1"), _plain("b.bin", "c2")],
                                        [], None, "sec", root, 2, lambda n: None,
                                        done={"a.bin"})
            self.assertEqual(self.fetched, ["c2"])
            self.assertEqual((root / "a.bin").read_bytes(), b"AB")   # untouched

    def test_sfc_files_without_container_is_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            errs = app._download_depot_fileset([], [_sfc_file("x.txt", 0, 1)], None,
                                               "sec", Path(d), 1, lambda n: None)
            self.assertEqual(len(errs), 1)
            self.assertEqual(errs[0][0], "SFC")


class CollectDepotGroups(unittest.TestCase):
    """Regression (1.4.3): every depot keeps ITS OWN small-files container."""
    def setUp(self):
        self._orig = app._cs_get_zlib
        manifests = {
            "m1": {"depot": {"items": [
                {"type": "DepotFile", "path": "base.bin", "chunks": []},
                {"type": "DepotFile", "path": "small1.txt", "sfcRef": {"offset": 0, "size": 5}},
                {"type": "DepotDirectory", "path": "data"}],
                "smallFilesContainer": _sfc("s1")}},
            "m2": {"depot": {"items": [
                {"type": "DepotFile", "path": "small2.txt", "sfcRef": {"offset": 0, "size": 3}}],
                "smallFilesContainer": _sfc("s2")}},
        }
        app._cs_get_zlib = lambda url: manifests[url.rsplit("/", 1)[-1]]

    def tearDown(self):
        app._cs_get_zlib = self._orig

    def test_one_group_per_depot_with_own_sfc(self):
        groups = app._collect_depot_groups([{"manifest": "m1"}, {"manifest": "m2"}])
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0]["sfc"], _sfc("s1"))
        self.assertEqual(groups[1]["sfc"], _sfc("s2"))
        self.assertEqual([f["path"] for f in groups[1]["sfced"]], ["small2.txt"])
        self.assertEqual([d["path"] for d in groups[0]["dirs"]], ["data"])
        self.assertEqual(app._group_total(groups[1]), len(CHUNKS["s2"]))


class SmallHelpers(unittest.TestCase):
    def test_parse_dlc_ids(self):
        keys = ["dlc:9:installer:1", "dlc:9:patch:2", "dlc:7:installer:3",
                "extra:1", "dlc::x", None, 5]
        self.assertEqual(app._parse_dlc_ids(keys), {"9", "7"})
        self.assertEqual(app._parse_dlc_ids(None), set())

    def test_depot_rel(self):
        self.assertEqual(app._depot_rel("\\a\\b.txt"), "a/b.txt")
        self.assertEqual(app._depot_rel("c/d"), "c/d")


if __name__ == "__main__":
    unittest.main()
