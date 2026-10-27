"""Depot language matching + install-selection (the 'which files' decisions)."""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app


class NormLang(unittest.TestCase):
    def test_prefix(self):
        self.assertEqual(app._norm_lang("en-US"), "en")
        self.assertEqual(app._norm_lang("zh-Hans"), "zh")
        self.assertEqual(app._norm_lang("PL"), "pl")
        self.assertEqual(app._norm_lang("pt_BR"), "pt")
        self.assertEqual(app._norm_lang(""), "")
        self.assertEqual(app._norm_lang(None), "")


class LangMatch(unittest.TestCase):
    def test_neutral_always_wanted(self):
        self.assertTrue(app._lang_match(["*"], {"pl"}))
        self.assertTrue(app._lang_match(["*"], {"de"}))

    def test_prefix_match(self):
        self.assertTrue(app._lang_match(["pl-PL"], {"pl"}))
        self.assertTrue(app._lang_match(["en-US", "de-DE"], {"de"}))

    def test_no_match(self):
        self.assertFalse(app._lang_match(["de-DE"], {"pl"}))
        self.assertFalse(app._lang_match([], {"pl"}))
        self.assertFalse(app._lang_match(None, {"pl"}))

    def test_default_wanted_is_english(self):
        self.assertTrue(app._lang_match(["en-US"]))
        self.assertFalse(app._lang_match(["de-DE"]))


class BuildTag(unittest.TestCase):
    """The updater trusts a build-id in the filename over GOG's (rounded) size."""
    def test_matches_gog_build_id(self):
        self.assertTrue(app._BUILD_TAG_RE.search("setup_x_1.0_(82340).exe"))
        self.assertTrue(app._BUILD_TAG_RE.search("setup_x_(89458)-2.bin"))

    def test_ignores_unversioned_names(self):
        self.assertIsNone(app._BUILD_TAG_RE.search("manual.pdf"))
        self.assertIsNone(app._BUILD_TAG_RE.search("soundtrack.zip"))


class SelectionRows(unittest.TestCase):
    def _manifest(self):
        return {
            "installers": [
                {"os": "windows", "lang": "en", "key": "installer:1", "name": "win-en"},
                {"os": "windows", "lang": "pl", "key": "installer:2", "name": "win-pl"},
                {"os": "linux",   "lang": "en", "key": "installer:3", "name": "lin-en"},
            ],
            "dlcs": [
                {"os": "windows", "lang": "en", "owned": True,  "key": "dlc:9:installer:1", "name": "dlc-owned"},
                {"os": "windows", "lang": "en", "owned": False, "key": "dlc:8:installer:1", "name": "dlc-unowned"},
                {"os": "windows", "lang": "en", "owned": True,  "key": "dlc:7:patch:1",     "name": "dlc-patch"},
            ],
            "language_packs": [
                {"lang": "pl", "key": "language_pack:1", "name": "lp-pl"},
                {"lang": "de", "key": "language_pack:2", "name": "lp-de"},
            ],
            "extras": [
                {"heavy": False, "key": "extra:1", "name": "manual"},
                {"heavy": True,  "key": "extra:2", "name": "old-version"},
            ],
        }

    def test_extras_only_when_no_installer(self):
        # Regression: a game whose only downloaded content is extras must NOT get
        # a full installer pulled by the updater.
        rows = app._update_selection_rows(self._manifest(), ["en", "pl"],
                                          include_installers=False)
        self.assertEqual({r["name"] for r in rows}, {"manual"})

    @unittest.skipUnless(app._MY_OS == "windows", "installer OS filter is platform-specific")
    def test_full_set_filters_os_lang_owned_heavy(self):
        names = {r["name"] for r in app._update_selection_rows(
            self._manifest(), ["en", "pl"], include_installers=True)}
        self.assertIn("win-en", names)
        self.assertIn("win-pl", names)
        self.assertNotIn("lin-en", names)        # wrong OS
        self.assertIn("dlc-owned", names)
        self.assertNotIn("dlc-unowned", names)   # not owned
        self.assertNotIn("dlc-patch", names)     # patch, not installer
        self.assertIn("lp-pl", names)
        self.assertNotIn("lp-de", names)         # language not requested
        self.assertIn("manual", names)
        self.assertNotIn("old-version", names)   # heavy / legacy


if __name__ == "__main__":
    unittest.main()
