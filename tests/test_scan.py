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


if __name__ == "__main__":
    unittest.main()
