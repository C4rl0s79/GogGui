"""Platform-specific paths — _ensure_content_dir creates the target and only
falls back next to the program when the target genuinely cannot be created."""
import os, sys, unittest, tempfile
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app


class EnsureContentDir(unittest.TestCase):
    def test_creates_missing_default(self):
        # A fresh default (e.g. ~/GOG/installers) doesn't exist yet — must be
        # created, NOT replaced by the program-dir fallback.
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "GOG" / "installers"
            fallback = Path(d) / "fallback"
            got = app._ensure_content_dir(target, fallback)
            self.assertEqual(got, target)
            self.assertTrue(target.is_dir())
            self.assertFalse(fallback.exists())

    def test_fallback_when_target_uncreatable(self):
        # Parent is a file → mkdir raises → fall back beside the program.
        with tempfile.TemporaryDirectory() as d:
            a_file = Path(d) / "afile"
            a_file.write_bytes(b"x")
            target = a_file / "sub"
            fallback = Path(d) / "fb"
            got = app._ensure_content_dir(target, fallback)
            self.assertEqual(got, fallback)
            self.assertTrue(fallback.is_dir())


class PlatformDefaults(unittest.TestCase):
    def test_my_os_known(self):
        self.assertIn(app._MY_OS, ("windows", "linux"))

    def test_builds_api_keys_off_platform(self):
        # Regression (1.4.0): the Galaxy builds endpoint must not be hardcoded to
        # windows — it embeds the detected platform.
        self.assertIn("/os/" + app._MY_OS + "/", app.GOG_BUILDS_API)


if __name__ == "__main__":
    unittest.main()
