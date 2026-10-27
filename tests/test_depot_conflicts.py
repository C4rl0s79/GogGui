"""Multi-language depot installs, launcher choice and .script setIni (1.4.4).
Modelled on The Witcher 3 next-gen (build 5.00c)."""
import os, sys, json, unittest, tempfile
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app


def _grp(*names, sfc=()):
    return {"plain": [{"path": n, "chunks": [{"compressedMd5": "x", "size": 1}]} for n in names],
            "sfced": [{"path": n, "sfcRef": {"offset": 0, "size": 1}} for n in sfc],
            "sfc": {"chunks": []} if sfc else None, "dirs": []}


def _w3():
    # neutral data depot + per-language depots that all ship the goggame files
    depots = [{"languages": ["*"]}, {"languages": ["ja-JP"]}, {"languages": ["pl-PL"]},
              {"languages": ["ja-JP"]}, {"languages": ["pl-PL"]}, {"languages": ["en-US"]}]
    groups = [_grp("bin\\x64_dx12\\witcher3.exe", sfc=["bin\\config\\base\\engine.ini"]),
              _grp(sfc=["goggame-1.info", "goggame-1.hashdb"]),
              _grp(sfc=["goggame-1.info", "goggame-1.hashdb"]),
              _grp("goggame-1.script"),
              _grp("goggame-1.script"),
              _grp(sfc=["goggame-1.info", "goggame-1.hashdb"])]
    return groups, depots


def _owner(groups, path):
    return [gi for gi, g in enumerate(groups)
            for f in g["plain"] + g["sfced"] if f["path"] == path]


class DepotConflicts(unittest.TestCase):
    def test_primary_language_wins_every_variant(self):
        groups, depots = _w3()
        app._resolve_depot_conflicts(groups, depots, "pl")
        self.assertEqual(_owner(groups, "goggame-1.info"), [2])      # pl only
        self.assertEqual(_owner(groups, "goggame-1.hashdb"), [2])
        self.assertEqual(_owner(groups, "goggame-1.script"), [4])    # pl only
        self.assertEqual(_owner(groups, "bin\\x64_dx12\\witcher3.exe"), [0])  # untouched

    def test_variant_missing_for_primary_is_dropped(self):
        # English ships no .script — keeping the ja/pl one would switch the game
        # to that language.
        groups, depots = _w3()
        app._resolve_depot_conflicts(groups, depots, "en")
        self.assertEqual(_owner(groups, "goggame-1.info"), [5])
        self.assertEqual(_owner(groups, "goggame-1.script"), [])

    def test_neutral_wins_over_non_primary_language(self):
        depots = [{"languages": ["*"]}, {"languages": ["pl-PL"]}]
        groups = [_grp("text.dat"), _grp("text.dat")]
        app._resolve_depot_conflicts(groups, depots, "en")
        self.assertEqual(_owner(groups, "text.dat"), [0])

    def test_single_owner_paths_untouched(self):
        depots = [{"languages": ["*"]}, {"languages": ["pl-PL"]}]
        groups = [_grp("a.bin"), _grp("pl_audio.bin")]
        self.assertEqual(app._resolve_depot_conflicts(groups, depots, "en"), 0)
        self.assertEqual(_owner(groups, "pl_audio.bin"), [1])

    def test_group_total_skips_unused_container(self):
        g = {"plain": [], "sfced": [], "sfc": {"chunks": [{"size": 999}]}, "dirs": []}
        self.assertEqual(app._group_total(g), 0)


class PlayTask(unittest.TestCase):
    def test_game_task_beats_primary_launcher(self):
        tasks = [{"isPrimary": True, "category": "launcher", "path": "REDprelauncher.exe"},
                 {"category": "game", "path": "bin/x64_dx12/witcher3.exe"},
                 {"category": "other", "path": ""}]
        self.assertEqual(app._pick_play_task(tasks)["path"], "bin/x64_dx12/witcher3.exe")

    def test_primary_game_preferred(self):
        tasks = [{"category": "game", "path": "tool.exe"},
                 {"isPrimary": True, "category": "game", "path": "game.exe"}]
        self.assertEqual(app._pick_play_task(tasks)["path"], "game.exe")

    def test_fallbacks(self):
        self.assertEqual(app._pick_play_task([{"isPrimary": True, "path": "a.exe"}])["path"], "a.exe")
        self.assertIsNone(app._pick_play_task([{"path": ""}]))


class SetIni(unittest.TestCase):
    def test_creates_and_updates_preserving_other_lines(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "sub" / "user.settings"
            app._ini_set(p, "Localization", "SpeechLanguage", "EN")
            self.assertIn("[Localization]", p.read_text())
            p.write_bytes(b"[Rendering]\r\nFoo=1\r\n\r\n[Localization]\r\nSpeechLanguage=EN\r\nText=EN\r\n")
            app._ini_set(p, "Localization", "SpeechLanguage", "PL")
            app._ini_set(p, "Localization", "Subtitles", "true")
            txt = p.read_bytes().decode()
            self.assertIn("Foo=1", txt)
            self.assertIn("SpeechLanguage=PL", txt)
            self.assertNotIn("SpeechLanguage=EN", txt)
            self.assertIn("Text=EN", txt)
            self.assertIn("Subtitles=true", txt)
            self.assertIn("\r\n", txt)                      # line endings kept

    def test_script_setini_with_userdocs(self):
        with tempfile.TemporaryDirectory() as d:
            root, docs = Path(d) / "game", Path(d) / "docs"
            root.mkdir()
            (root / "goggame-1.script").write_text(json.dumps({"actions": [
                {"install": {"action": "setIni", "arguments": {
                    "filename": "{userdocs}/The Witcher 3/user.settings",
                    "section": "Localization", "keyName": "SpeechLanguage", "keyValue": "EN"}}},
                {"install": {"action": "setRegistry", "arguments": {"valueName": "SKU"}}},
                {"install": {"action": "setIni", "arguments": {
                    "filename": "{userdocs}/The Witcher 3/user.settings",
                    "section": "Localization", "keyName": "SpeechLanguage", "keyValue": "PL"}}},
            ]}), encoding="utf-8")
            orig = app._user_documents
            app._user_documents = lambda: docs
            try:
                app._apply_support_data(root, "1")
            finally:
                app._user_documents = orig
            txt = (docs / "The Witcher 3" / "user.settings").read_text()
            self.assertIn("SpeechLanguage=PL", txt)          # applied in order


if __name__ == "__main__":
    unittest.main()
