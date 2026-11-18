"""Install/DLC detection on disk — in-progress installs must not read as done,
and installed-DLC detection must key off goggame-{id}.info."""
import os, sys, unittest, tempfile
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app


class ScanInstalled(unittest.TestCase):
    def setUp(self):
        self._orig = app.GOG_GAMES

    def tearDown(self):
        app.GOG_GAMES = self._orig

    def test_skips_dir_with_inprogress_marker(self):
        # Regression (1.1.1/1.4.2): a directory still carrying the resume marker
        # is an install in progress, not a finished game.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            app.GOG_GAMES = root
            done_game = root / "Game One"
            done_game.mkdir()
            (done_game / "goggame-100.info").write_text("{}", encoding="utf-8")
            wip_game = root / "Game Two"
            wip_game.mkdir()
            (wip_game / "goggame-200.info").write_text("{}", encoding="utf-8")
            (wip_game / app._DEPOT_STATE_NAME).write_text("{}", encoding="utf-8")

            res = app.scan_installed_games()
            self.assertIn("100", res)
            self.assertNotIn("200", res)


class InstalledDlcIds(unittest.TestCase):
    def test_lists_dlc_infos_excluding_base(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            for pid in ("100", "200", "300"):
                (p / f"goggame-{pid}.info").write_text("{}", encoding="utf-8")
            self.assertEqual(set(app._installed_dlc_ids(p, "100")), {"200", "300"})

    def test_no_install_dir(self):
        self.assertEqual(app._installed_dlc_ids(None, "1"), [])


class ScanDownloadedMeta(unittest.TestCase):
    """Regression (1.5.0–1.6.1): a folder holding only the game metadata written by
    export_game_meta read as a downloaded game (every owned game showed „Pobrano”)."""
    META = ("product_{s}.json", "galaxy_{s}.json", "game-details.json", "icon_{s}.png",
            "logo_{s}.jpg", "boxart_{s}.jpg", "background_{s}.jpg", "titlelogo_{s}.png",
            "iconsquare_{s}.png", "changelog_{s}.html", "product_{s}.json.tmp")

    def _folder(self, root: Path, slug: str) -> Path:
        d = root / slug
        d.mkdir()
        for name in self.META:
            (d / name.format(s=slug)).write_bytes(b"x")
        return d

    def test_metadata_only_is_not_downloaded(self):
        with tempfile.TemporaryDirectory() as t:
            d = self._folder(Path(t), "kingdom_come_deliverance")
            self.assertIsNone(app._scan_download_dir(d))

    def test_installer_and_extras_still_counted(self):
        with tempfile.TemporaryDirectory() as t:
            d = self._folder(Path(t), "anachronox")
            (d / "setup_anachronox.exe").write_bytes(b"xx")
            (d / "manual.pdf").write_bytes(b"xxx")        # root extra (extras_subdir off)
            (d / "extras").mkdir()
            (d / "extras" / "soundtrack.zip").write_bytes(b"xxxx")
            info = app._scan_download_dir(d)
            self.assertEqual(info["files"], ["setup_anachronox.exe"])
            self.assertEqual(info["extras_files"], ["manual.pdf", "soundtrack.zip"])
            self.assertEqual(info["extras_size"], 7)

    def test_extras_dir_alone_counts(self):
        with tempfile.TemporaryDirectory() as t:
            d = self._folder(Path(t), "some_game")
            (d / "extras").mkdir()
            (d / "extras" / "artbook.pdf").write_bytes(b"x")
            info = app._scan_download_dir(d)
            self.assertFalse(info["has_installer"])
            self.assertEqual(info["extras_files"], ["artbook.pdf"])


if __name__ == "__main__":
    unittest.main()
