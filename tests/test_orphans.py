"""Destructive updater behavior — _cleanup_orphans must only delete stale files,
never the user's expected files or unpacked sub-folders, and only under BASE."""
import os, sys, unittest, tempfile
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app


class CleanupOrphans(unittest.TestCase):
    def setUp(self):
        self._base = app.BASE

    def tearDown(self):
        app.BASE = self._base

    def test_removes_only_orphans_keeps_expected_and_subdirs(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            app.BASE = base
            game = base / "slug"
            game.mkdir()
            (game / "setup_keep_(500).exe").write_bytes(b"x")   # expected
            (game / "setup_old_(400).exe").write_bytes(b"x")    # orphan (old build)
            extras = game / "extras"
            extras.mkdir()
            (extras / "manual.pdf").write_bytes(b"x")           # expected
            (extras / "old.zip").write_bytes(b"x")              # orphan
            sub = extras / "unpacked"                            # unpacked subdir
            sub.mkdir()
            (sub / "inside.txt").write_bytes(b"x")

            expected = {
                (str(game), "setup_keep_(500).exe"): {},
                (str(extras), "manual.pdf"): {},
            }
            removed = {Path(r).name for r in app._cleanup_orphans(game, extras, expected)}

            self.assertEqual(removed, {"setup_old_(400).exe", "old.zip"})
            self.assertTrue((game / "setup_keep_(500).exe").exists())
            self.assertTrue((extras / "manual.pdf").exists())
            # A whole unpacked sub-folder must survive (iterdir + is_file only).
            self.assertTrue(sub.is_dir())
            self.assertTrue((sub / "inside.txt").exists())

    def test_never_touches_files_outside_base(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            app.BASE = Path(d1)
            outside = Path(d2)
            (outside / "setup_x_(1).exe").write_bytes(b"x")
            removed = app._cleanup_orphans(outside, outside, {})
            self.assertEqual(removed, [])
            self.assertTrue((outside / "setup_x_(1).exe").exists())


if __name__ == "__main__":
    unittest.main()
