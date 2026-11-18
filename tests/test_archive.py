"""Local depot archive: per-game sequential migration, safe cleanup, offline
install. Everything runs against a small synthetic "GOG" (fake API, CDN,
build meta and manifests) in temporary directories — no network, no real
installers, no real user settings."""
import hashlib, json, os, sys, tempfile, unittest, zlib
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app
import depot_archive as DA


class _Crash(BaseException):
    """Simulates the process dying (passes through `except Exception`)."""


def _chunk(data: bytes, cdn: dict) -> dict:
    comp = zlib.compress(data)
    m = hashlib.md5(comp).hexdigest()
    cdn[m] = comp
    return {"compressedMd5": m, "compressedSize": len(comp),
            "md5": hashlib.md5(data).hexdigest(), "size": len(data)}


def _file(path: str, data: bytes, cdn: dict) -> dict:
    return {"type": "DepotFile", "path": path, "chunks": [_chunk(data, cdn)],
            "md5": hashlib.md5(data).hexdigest()}


SHARED = b"SHARED-RUNTIME-BYTES" * 3


class World:
    """Synthetic GOG: products, Galaxy builds, depot manifests, CDN chunks,
    download manifests and offline installers on disk."""

    def __init__(self, base: Path):
        self.base = base
        self.cdn, self.manifests, self.metas, self.builds = {}, {}, {}, {}
        self.dl_manifests, self.games, self.deps = {}, [], {}

    def add_game(self, pid: str, slug: str, *, langs=("en", "pl"), disk_langs=("en",),
                 version="1.0", build_id="B1", dlc_files=True, dlc_meta=True,
                 deps=(), build_version=None, installers=True):
        cdn, mans = self.cdn, self.manifests
        neutral_id = f"{pid}n{build_id}"
        sfc_blob = b"aaaabbbb"
        mans[neutral_id] = {"depot": {"items": [
            {"type": "DepotDirectory", "path": "data"},
            _file("bin\\game.exe", f"GAME-{pid}-{build_id}".encode(), cdn),
            _file("data\\shared.dat", SHARED, cdn),
            {"type": "DepotFile", "path": "sfc\\a.txt", "sfcRef": {"offset": 0, "size": 4}},
            {"type": "DepotFile", "path": "sfc\\b.txt", "sfcRef": {"offset": 4, "size": 4}},
        ], "smallFilesContainer": {"chunks": [_chunk(sfc_blob, cdn)]}}}
        depots = [{"productId": pid, "languages": ["*"], "manifest": neutral_id}]
        for l in langs:
            mid = f"{pid}{l}{build_id}"
            mans[mid] = {"depot": {"items": [
                _file(f"lang\\{l}.txt", f"{l}-{pid}".encode(), cdn),
                _file(f"goggame-{pid}.info",
                      json.dumps({"gameId": pid, "language": l, "playTasks": []}).encode(), cdn),
            ]}}
            depots.append({"productId": pid, "languages": [{"en": "en-US", "pl": "pl-PL",
                                                             "de": "de-DE"}[l]], "manifest": mid})
        d1, d2 = f"{pid}1", f"{pid}2"
        products = [{"productId": pid, "name": slug}]
        if dlc_files:
            mid = f"{d1}n{build_id}"
            mans[mid] = {"depot": {"items": [_file(f"dlc\\{d1}.pak", f"DLC-{d1}".encode(), cdn)]}}
            depots.append({"productId": d1, "languages": ["*"], "manifest": mid})
            products.append({"productId": d1, "name": "DLC with files"})
        if dlc_meta:
            products.append({"productId": d2, "name": "DLC metadata only"})
        for dep in deps:
            mid = f"dep{dep}00"
            self.deps[dep] = (mid, {"depot": {"items": [
                _file(f"__redist\\{dep}\\{dep}.exe", f"REDIST-{dep}".encode(), cdn)]}})
        self.metas[pid] = {"buildId": build_id, "installDirectory": f"{slug} dir",
                           "depots": depots, "products": products,
                           "dependencies": list(deps)}
        self.builds[pid] = {"build_id": build_id, "version_name": build_version or version,
                            "link": f"meta://{pid}"}

        folder = self.base / slug
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "extras").mkdir(exist_ok=True)
        (folder / "extras" / "manual.pdf").write_bytes(b"%PDF manual")
        rows, dlcs = [], []
        sizes = {"en": (10, 20), "pl": (15,), "de": (16,)}
        for l in ("en", "pl", "de"):
            names = ([f"setup_{slug}_{version}_(1234).exe", f"setup_{slug}_{version}_(1234)-1.bin"]
                     if l == "en" else [f"setup_{slug}_{l}_{version}_(1234).exe"])
            parts = [{"size": s, "downlink": f"dl://{n}"} for n, s in zip(names, sizes[l])]
            rows.append({"key": f"installer:{l}", "category": "installer", "os": app._MY_OS,
                         "lang": l, "version": version, "name": f"{slug} {l}", "parts": parts})
            if installers and l in disk_langs:
                for n, s in zip(names, sizes[l]):
                    (folder / n).write_bytes(b"I" * s)
        for did, size in ((d1, 7), (d2, 8)):
            n = f"setup_{slug}_dlc{did}_(1234).exe"
            dlcs.append({"key": f"dlc:{did}:installer:1", "category": "dlc", "os": app._MY_OS,
                         "lang": "en", "owned": True, "version": version,
                         "name": f"DLC {did}", "parts": [{"size": size, "downlink": f"dl://{n}"}]})
            if installers:
                (folder / n).write_bytes(b"D" * size)
        if installers:
            (folder / f"setup_{slug}_0.9_(1000).exe").write_bytes(b"O" * 11)   # old version
        self.dl_manifests[pid] = {"ok": True, "installers": rows, "dlcs": dlcs, "patches": [],
                                  "language_packs": [], "extras": []}
        self.games.append({"id": pid, "slug": slug, "game_key": slug, "title": slug.title(),
                           "product": {"id": int(pid)}})
        return folder


class ArchiveTestBase(unittest.TestCase):
    PATCH = ("BASE", "GOG_GAMES", "get_settings", "scan_games", "get_download_manifest",
             "_access_token_box", "_resolve_downlink", "_pick_build", "_cs_get_zlib",
             "_cdn_depot_manifest", "_dependency_manifests", "_get_secure_link",
             "_dependency_secure_link", "_fetch_chunk_raw", "_load_purchase_ranks",
             "log", "_MIG_TRACE", "_delete_installer_file", "_free_bytes", "_send_js",
             "_owned_ids_cached", "_fetch_v2_game", "_fetch_image")

    def setUp(self):
        self._orig = {k: getattr(app, k) for k in self.PATCH}
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        app.BASE = root / "inst"
        app.GOG_GAMES = root / "games"
        app.BASE.mkdir()
        app.GOG_GAMES.mkdir()
        self.w = World(app.BASE)
        self.settings = {"archive_mode": True, "update_langs": ["en"], "depot_langs": ["en"]}
        self.fetched, self.fail_fetch = [], None
        self.trace = app._MIG_TRACE = []
        self.sent = []
        w = self.w

        app.get_settings = lambda: {**app.DEFAULT_SETTINGS, **self.settings}
        app.scan_games = lambda: list(w.games)
        app.get_download_manifest = lambda gid: w.dl_manifests[str(gid)]
        app._access_token_box = lambda: {"access": "SECRET-TOKEN", "refresh": "R", "tokens": {}}
        app._resolve_downlink = lambda dl, box: {"downlink": "https://cdn.example/x/" + dl[5:]}
        app._pick_build = lambda pid: w.builds[str(pid)]
        app._cs_get_zlib = lambda url: w.metas[url.split("://", 1)[1]]
        app._cdn_depot_manifest = lambda d: json.loads(json.dumps(w.manifests[d["manifest"]]))
        app._dependency_manifests = lambda ids: (
            [{"id": i, "manifest": w.deps[i][0], "man": w.deps[i][1]} for i in ids if i in w.deps],
            {i for i in ids if i not in w.deps})
        app._get_secure_link = lambda pid, box: f"sec://{pid}"
        app._dependency_secure_link = lambda: "sec://dep"
        app._load_purchase_ranks = lambda: {}
        app.log = lambda m: None
        app._send_js = lambda d: self.sent.append(d)
        # owned products: every game and every DLC of the synthetic world (tests change it as needed)
        self.owned = None
        app._owned_ids_cached = lambda max_age=1800: (self.owned if self.owned is not None else
                                                      {str(x["productId"]) for m in w.metas.values() for x in m["products"]})
        app._fetch_v2_game = lambda pid: None          # no network in tests
        app._fetch_image = lambda url: None

        def fetch(secure, md5):
            if self.fail_fetch:
                self.fail_fetch(md5)
            self.fetched.append(md5)
            return w.cdn[md5]
        app._fetch_chunk_raw = fetch
        app._cancel.clear()

    def tearDown(self):
        for k, v in self._orig.items():
            setattr(app, k, v)
        self._tmp.cleanup()

    # helpers
    def arc(self):
        return app._archive()

    def folder(self, slug):
        return app.BASE / slug

    META_FILE = __import__("re").compile(r"^(product_|galaxy_|icon_|logo_|boxart_|background_|titlelogo_|iconsquare_).+|game-details\.json$")

    def installers(self, slug):
        """files of the game folder except its metadata (product_*.json, grafiki — export_game_meta)"""
        return sorted(p.name for p in self.folder(slug).iterdir() if p.is_file() and not self.META_FILE.match(p.name))


# ══════════════════════════════════════════════════════════════════════════════

class OptionOff(ArchiveTestBase):
    def test_disabled_option_keeps_legacy_update_all(self):
        self.settings["archive_mode"] = False
        self.w.add_game("100", "alpha")
        calls = []
        orig = app._update_worker
        app._update_worker = lambda gid, extras_only=False: calls.append((gid, extras_only)) or True
        try:
            self.assertTrue(app._update_all_worker())
        finally:
            app._update_worker = orig
        self.assertEqual(calls, [("100", False)])           # classic updater, installers incl.
        self.assertFalse((app.BASE / "_depots").exists())   # archive never touched
        self.assertEqual(self.fetched, [])

    def test_default_is_off_and_enabling_alone_changes_nothing(self):
        self.assertFalse(app.DEFAULT_SETTINGS["archive_mode"])
        self.w.add_game("100", "alpha")
        before = self.installers("alpha")
        self.assertEqual(app._archive_status_map(), {})     # just reading status
        self.assertEqual(self.installers("alpha"), before)
        self.assertFalse((app.BASE / "_depots").exists())


class Inventory(ArchiveTestBase):
    def test_exe_bin_and_dlc_assignment(self):
        self.w.add_game("100", "alpha")
        inv = app._inventory_installers(self.w.dl_manifests["100"], {}, self.folder("alpha"))
        st = {e["name"]: e for e in inv["files"]}
        self.assertEqual(st["setup_alpha_1.0_(1234).exe"]["status"], "assigned")
        self.assertEqual(st["setup_alpha_1.0_(1234)-1.bin"]["kind"], "base")   # BIN → its EXE's product
        self.assertEqual(st["setup_alpha_1.0_(1234)-1.bin"]["langs"], ["en"])
        self.assertEqual(st["setup_alpha_dlc1001_(1234).exe"]["kind"], "dlc")
        self.assertEqual(st["setup_alpha_dlc1001_(1234).exe"]["dlc"], "1001")
        self.assertEqual(st["setup_alpha_0.9_(1000).exe"]["status"], "unassigned")
        self.assertNotIn("manual.pdf", st)                    # extras are never inventoried

    def test_api_sizes_rounded_to_mib_still_match(self):
        # Regression: the GOG products API reports e.g. 1068498944 (1019 MiB)
        # for a 1069242312-byte installer — exact comparison matched nothing.
        self.w.add_game("100", "alpha")
        exe = self.folder("alpha") / "setup_alpha_1.0_(1234).exe"
        exe.write_bytes(b"I" * (2 * 1024 * 1024 + 743368))
        man = self.w.dl_manifests["100"]
        man["installers"][0]["parts"][0]["size"] = 2 * 1024 * 1024
        inv = app._inventory_installers(man, {}, self.folder("alpha"))
        e = next(x for x in inv["files"] if x["name"] == exe.name)
        self.assertEqual(e["status"], "assigned")
        self.assertEqual(e["size"], exe.stat().st_size)          # exact disk size is recorded

    def test_ambiguous_file_is_not_assigned(self):
        self.w.add_game("100", "alpha")
        man = self.w.dl_manifests["100"]
        # The same file (name + size) claimed by the base game AND a DLC.
        man["dlcs"][0]["parts"] = [dict(man["installers"][0]["parts"][0])]
        inv = app._inventory_installers(man, {}, self.folder("alpha"))
        e = next(x for x in inv["files"] if x["name"] == "setup_alpha_1.0_(1234).exe")
        self.assertEqual(e["status"], "ambiguous")

    def test_size_mismatch_is_not_assigned(self):
        self.w.add_game("100", "alpha")
        (self.folder("alpha") / "setup_alpha_1.0_(1234).exe").write_bytes(b"x" * (3 * 1024 * 1024))
        inv = app._inventory_installers(self.w.dl_manifests["100"], {}, self.folder("alpha"))
        e = next(x for x in inv["files"] if x["name"] == "setup_alpha_1.0_(1234).exe")
        self.assertEqual(e["status"], "unassigned")


class Migration(ArchiveTestBase):
    def _listed_on_gog(self, i=-1, os_name=None):
        """The library product lists an installer (GOG `expand=downloads`) — as for a game bought after the last
        run, of which nothing is on disk yet."""
        self.w.games[i]["product"]["downloads"] = {"installers": [{"os": os_name or app._MY_OS}]}

    def test_update_all_archives_game_never_downloaded(self):
        self.w.add_game("100", "alpha")
        self.assertTrue(app._archive_all_worker())
        self.w.add_game("300", "gamma", installers=False)      # new on the account: no installers, no record
        self._listed_on_gog()
        self.assertTrue(app._archive_all_worker())
        rec = self.arc().read_record("300", "B1")
        self.assertEqual(rec["state"], DA.STATE_COMPLETE)
        self.assertEqual((rec["scope"]["languages"], rec["scope"]["dlcs"]), (["en", "pl"], ["3001", "3002"]))
        self.assertTrue((self.folder("gamma") / "extras" / "manual.pdf").exists())
        rep = [m for m in self.sent if m.get("type") == "migration_report"][-1]["report"]
        self.assertEqual([x["title"] for x in rep["updated"]], ["Gamma"])

    def test_update_one_game_archives_game_never_downloaded(self):
        self.w.add_game("300", "gamma", installers=False)
        self._listed_on_gog()
        self.assertTrue(app._archive_all_worker(only_ids={"300"}))
        self.assertEqual(self.arc().read_record("300", "B1")["state"], DA.STATE_COMPLETE)

    def test_update_all_leaves_out_entries_without_installer(self):
        self.w.add_game("300", "gamma", installers=False)       # goodies-only: GOG lists no installer
        self.w.add_game("400", "delta", installers=False)
        self._listed_on_gog(os_name="mac")                     # installer only for another OS
        self.assertTrue(app._archive_all_worker())
        self.assertIsNone(self.arc().read_record("300", "B1"))
        self.assertIsNone(self.arc().read_record("400", "B1"))
        self.assertEqual(self.fetched, [])                     # nothing downloaded

    def test_migration_without_version_change(self):
        self.w.add_game("100", "alpha")
        self.assertTrue(app._archive_all_worker())
        left = self.installers("alpha")
        # replaced: EN exe+bin, DLC with files, metadata-only DLC; kept: old version
        self.assertEqual(left, ["setup_alpha_0.9_(1000).exe"])
        self.assertTrue((self.folder("alpha") / "extras" / "manual.pdf").exists())   # extras kept
        rec = self.arc().read_record("100", "B1")
        self.assertEqual(rec["state"], DA.STATE_COMPLETE)
        # every language of the build (EN installer on disk, PL only in depots) and every owned DLC
        self.assertEqual(rec["scope"]["languages"], ["en", "pl"])
        self.assertEqual(rec["scope"]["dlcs"], ["1001", "1002"])
        self.assertEqual(self.arc().read_journal("100")["phase"], DA.PH_DONE)
        rep = next(m for m in self.sent if m.get("type") == "migration_report")["report"]
        self.assertEqual([x["title"] for x in rep["migrated"]], ["Alpha"])
        self.assertEqual(rep["migrated"][0]["version_change"], "")
        self.assertEqual(rep["deleted_bytes"], 10 + 20 + 7 + 8)
        self.assertGreater(rep["added_bytes"], 0)              # reported separately

    def test_strict_order_one_game_at_a_time(self):
        self.w.add_game("100", "alpha")
        self.w.add_game("200", "beta")
        a_exe = self.folder("alpha") / "setup_alpha_1.0_(1234).exe"
        seen_b_fetch = []

        def fail(md5):
            if md5 in self._chunks_of("200") - self._chunks_of("100") and not seen_b_fetch:
                seen_b_fetch.append(a_exe.exists())
        self.fail_fetch = fail
        self.assertTrue(app._archive_all_worker())
        self.assertEqual(seen_b_fetch, [False])     # A's installer gone before B's first chunk
        stages = [(p, s) for p, s in self.trace]
        a_last = max(i for i, (p, s) in enumerate(stages) if p == "100")
        b_first = min(i for i, (p, s) in enumerate(stages) if p == "200")
        self.assertLess(a_last, b_first)
        a = [s for p, s in stages if p == "100"]
        for before, after in (("download", "verify"), ("verify", "committed"),
                              ("committed", "cleanup"), ("cleanup", "done")):
            self.assertLess(a.index(before), a.index(after))

    def _chunks_of(self, pid):
        out = set()
        for d in self.w.metas[pid]["depots"]:
            out |= {c["compressedMd5"] for c in DA.manifest_chunks(self.w.manifests[d["manifest"]])}
        return out

    def _chunks_of_shared(self):
        return {hashlib.md5(zlib.compress(SHARED)).hexdigest()}

    def test_verification_failure_keeps_installers_and_queue_continues(self):
        # deep_verify: the full re-read pass runs over every chunk (fast mode
        # checks fresh chunks in memory instead — see the test below)
        self.settings["deep_verify"] = True
        self.w.add_game("100", "alpha")
        self.w.add_game("200", "beta")
        before = self.installers("alpha")
        orig = DA.DepotArchive.verify_chunks
        calls = {"n": 0}

        def bad_verify(arc_self, chunks, cancel=None, progress=None, workers=1):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"missing": [], "corrupt": [chunks[0]["compressedMd5"]], "checked": 1}
            return orig(arc_self, chunks, cancel, progress, workers)
        DA.DepotArchive.verify_chunks = bad_verify
        try:
            self.assertFalse(app._archive_all_worker())
        finally:
            DA.DepotArchive.verify_chunks = orig
        self.assertEqual(self.installers("alpha"), before)              # untouched
        self.assertEqual(self.arc().read_record("100", "B1")["state"], DA.STATE_INCOMPLETE)
        self.assertEqual(self.installers("beta"), ["setup_beta_0.9_(1000).exe"])   # B migrated
        rep = next(m for m in self.sent if m.get("type") == "migration_report")["report"]
        self.assertEqual([e["title"] for e in rep["errors"]], ["Alpha"])

    def test_download_failure_keeps_installers(self):
        self.w.add_game("100", "alpha")
        before = self.installers("alpha")

        def boom(md5):
            raise RuntimeError("CDN 503")
        self.fail_fetch = boom
        self.assertFalse(app._archive_all_worker())
        self.assertEqual(self.installers("alpha"), before)

    def test_cleanup_failure_pauses_queue_then_resumes_cleanup_only(self):
        self.w.add_game("100", "alpha")
        self.w.add_game("200", "beta")

        def locked(p):
            raise PermissionError("plik używany przez inny proces")
        app._delete_installer_file = locked
        self.assertFalse(app._archive_all_worker())
        self.assertNotIn("200", {p for p, _ in self.trace})            # B never started
        j = self.arc().read_journal("100")
        self.assertEqual(j["phase"], DA.PH_CLEANUP_FAILED)
        self.assertEqual(self.arc().read_record("100", "B1")["state"], DA.STATE_COMPLETE)
        self.assertIn("100", app._archive_status_map())
        self.assertTrue(app._archive_status_map()["100"]["pending_cleanup"])

        # "restart": deletion works again — A's cleanup resumes WITHOUT downloads
        app._delete_installer_file = self._orig["_delete_installer_file"]
        self.fetched.clear()
        self.trace.clear()
        self.assertTrue(app._archive_all_worker())
        self.assertEqual(self.installers("alpha"), ["setup_alpha_0.9_(1000).exe"])
        self.assertTrue(set(self.fetched).isdisjoint(self._chunks_of("100")))
        self.assertEqual(self.trace[0], ("100", "start"))              # pending cleanup first
        self.assertEqual(self.installers("beta"), ["setup_beta_0.9_(1000).exe"])

    def test_partial_cleanup_continues_only_committed_list(self):
        self.w.add_game("100", "alpha")
        n = {"k": 0}
        orig = self._orig["_delete_installer_file"]

        def die_after_one(p):
            n["k"] += 1
            if n["k"] == 2:
                raise _Crash()
            orig(p)
        app._delete_installer_file = die_after_one
        with self.assertRaises(_Crash):
            app._archive_all_worker()
        j = self.arc().read_journal("100")
        self.assertEqual(j["phase"], DA.PH_CLEANUP)
        self.assertEqual(len(j["deleted"]), 1)
        # a file the user drops into the folder now is NOT on the frozen list
        stray = self.folder("alpha") / "setup_alpha_new_(9999).exe"
        stray.write_bytes(b"x" * 10)
        app._delete_installer_file = orig
        self.fetched.clear()
        self.assertTrue(app._archive_all_worker())
        self.assertTrue(stray.exists())
        self.assertEqual(self.fetched, [])
        self.assertEqual(self.arc().read_journal("100")["phase"], DA.PH_DONE)

    def test_resume_after_crash_during_download_does_not_refetch(self):
        self.w.add_game("100", "alpha")
        n = {"k": 0}

        def crash_on_third(md5):
            n["k"] += 1
            if n["k"] == 3:
                raise _Crash()
        self.fail_fetch = crash_on_third
        app.get_download_threads_orig = app.get_download_threads
        app.get_download_threads = lambda: 1           # deterministic order
        try:
            with self.assertRaises(_Crash):
                app._archive_all_worker()
            got_first = list(self.fetched)
            self.assertGreaterEqual(len(got_first), 2)
            self.assertEqual(self.arc().read_record("100", "B1")["state"], DA.STATE_INCOMPLETE)
            self.assertEqual(len(self.installers("alpha")), 5)         # nothing deleted
            self.fail_fetch = None
            self.fetched.clear()
            self.assertTrue(app._archive_all_worker())
            self.assertTrue(set(self.fetched).isdisjoint(got_first))   # idempotent
            self.assertEqual(len(self.fetched), 1)                     # only the lost chunk
        finally:
            app.get_download_threads = app.get_download_threads_orig

    def test_resume_after_crash_during_verification(self):
        self.w.add_game("100", "alpha")
        orig = DA.DepotArchive.verify_chunks

        def crash(*a, **k):
            raise _Crash()
        DA.DepotArchive.verify_chunks = crash
        try:
            with self.assertRaises(_Crash):
                app._archive_all_worker()
        finally:
            DA.DepotArchive.verify_chunks = orig
        self.assertEqual(len(self.installers("alpha")), 5)
        self.fetched.clear()
        self.assertTrue(app._archive_all_worker())
        self.assertEqual(self.fetched, [])                              # data already there
        self.assertEqual(self.arc().read_record("100", "B1")["state"], DA.STATE_COMPLETE)

    def test_second_run_is_unchanged(self):
        self.w.add_game("100", "alpha")
        app._archive_all_worker()
        self.fetched.clear()
        self.sent.clear()
        self.assertTrue(app._archive_all_worker())
        self.assertEqual(self.fetched, [])
        rep = next(m for m in self.sent if m.get("type") == "migration_report")["report"]
        self.assertEqual(rep["deleted_bytes"], 0)

    def test_corrupt_download_is_caught_in_memory_and_queue_continues(self):
        self.w.add_game("100", "alpha")
        self.w.add_game("200", "beta")
        before = self.installers("alpha")
        # GOG's plain MD5 of one alpha chunk disagrees with its bytes
        mid = "100nB1"
        self.w.manifests[mid]["depot"]["items"][1]["chunks"][0]["md5"] = "0" * 32
        self.assertFalse(app._archive_all_worker())
        self.assertEqual(self.installers("alpha"), before)
        self.assertEqual(self.arc().read_record("100", "B1")["state"], DA.STATE_INCOMPLETE)
        self.assertEqual(self.installers("beta"), ["setup_beta_0.9_(1000).exe"])
        rep = next(m for m in self.sent if m.get("type") == "migration_report")["report"]
        self.assertEqual([e["title"] for e in rep["errors"]], ["Alpha"])

    def _count_verified(self):
        seen = []
        orig = DA.DepotArchive.verify_chunks

        def counting(arc_self, chunks, cancel=None, progress=None, workers=1):
            seen.extend((c.get("compressedMd5") or "").lower() for c in chunks)
            return orig(arc_self, chunks, cancel, progress, workers)
        DA.DepotArchive.verify_chunks = counting
        self.addCleanup(setattr, DA.DepotArchive, "verify_chunks", orig)
        return seen

    def test_fresh_downloads_are_not_re_read(self):
        self.w.add_game("100", "alpha")
        seen = self._count_verified()
        self.assertTrue(app._archive_all_worker())
        self.assertEqual(seen, [])                     # all checked in memory
        self.assertEqual(self.arc().read_record("100", "B1")["state"], DA.STATE_COMPLETE)

    def test_second_run_skips_verification_unless_deep(self):
        self.w.add_game("100", "alpha")
        app._archive_all_worker()
        seen = self._count_verified()
        # a vanished chunk is not noticed by the trusted fast path…
        lost = next(iter(self._chunks_of("100")))
        self.arc().chunk_path(lost).unlink()
        self.fetched.clear()
        self.assertTrue(app._archive_all_worker())
        self.assertEqual((seen, self.fetched), ([], []))
        # …but deep_verify re-checks presence and fetches it back
        self.settings["deep_verify"] = True
        self.assertTrue(app._archive_all_worker())
        self.assertEqual(self.fetched, [lost])
        self.assertIn(lost, seen)

    def test_new_build_verifies_only_new_chunks_and_gc_runs_once(self):
        self.w.add_game("100", "alpha")
        self.w.add_game("200", "beta")
        app._archive_all_worker()
        self.w.add_game("100", "alpha", build_id="B2", installers=False)
        self.w.add_game("200", "beta", build_id="B2", installers=False)
        self.w.games = self.w.games[:2]
        seen = self._count_verified()
        gcs = []
        orig_gc = DA.DepotArchive.gc

        def counting_gc(arc_self, candidates=None):
            gcs.append(candidates)
            return orig_gc(arc_self, candidates)
        DA.DepotArchive.gc = counting_gc
        self.addCleanup(setattr, DA.DepotArchive, "gc", orig_gc)
        self.fetched.clear()
        self.assertTrue(app._archive_all_worker())
        self.assertEqual(seen, [])                     # shared chunks trusted, new ones fresh
        self.assertNotIn(self._chunks_of_shared().pop(), self.fetched)
        self.assertEqual(len(gcs), 1)                  # one sweep for the whole run
        self.assertIsNotNone(gcs[0])                   # targeted, not a full tree walk
        arc = self.arc()
        self.assertIsNone(arc.read_record("100", "B1"))
        self.assertFalse(arc.has_chunk(hashlib.md5(zlib.compress(b"GAME-100-B1")).hexdigest()))
        self.assertTrue(arc.has_chunk(hashlib.md5(zlib.compress(SHARED)).hexdigest()))

    def test_not_enough_space(self):
        self.w.add_game("100", "alpha")
        app._free_bytes = lambda p: 1024
        self.assertFalse(app._archive_all_worker())
        self.assertEqual(len(self.installers("alpha")), 5)
        self.assertEqual(self.fetched, [])
        self.assertFalse(list((self.arc().root / "chunks").rglob("*")) if
                         (self.arc().root / "chunks").exists() else [])

    def test_language_not_in_build_keeps_its_installer(self):
        self.w.add_game("100", "alpha", langs=("en", "pl"), disk_langs=("en", "de"))
        app._archive_all_worker()
        left = self.installers("alpha")
        self.assertIn("setup_alpha_de_1.0_(1234).exe", left)            # no silent switch
        self.assertNotIn("setup_alpha_1.0_(1234).exe", left)
        rec = self.arc().read_record("100", "B1")
        self.assertEqual(rec["scope"]["languages"], ["en", "pl"])        # all of the build; DE is not in it

    def test_pl_and_en_installers_archive_both(self):
        self.w.add_game("100", "alpha", disk_langs=("en", "pl"))
        app._archive_all_worker()
        rec = self.arc().read_record("100", "B1")
        self.assertEqual(rec["scope"]["languages"], ["en", "pl"])
        self.assertEqual(rec["collisions"], 1)                         # goggame-100.info variants
        self.assertEqual(self.installers("alpha"), ["setup_alpha_0.9_(1000).exe"])

    def test_dlc_not_in_build_keeps_its_installer(self):
        self.w.add_game("100", "alpha", dlc_meta=False)      # 1002 unknown to the Galaxy build
        app._archive_all_worker()
        self.assertIn("setup_alpha_dlc1002_(1234).exe", self.installers("alpha"))
        self.assertNotIn("setup_alpha_dlc1001_(1234).exe", self.installers("alpha"))
        self.assertEqual(self.arc().read_record("100", "B1")["scope"]["dlcs"], ["1001"])

    def test_download_in_archive_mode_stores_depots_not_installers(self):
        self.w.add_game("100", "alpha", installers=False)
        man = self.w.dl_manifests["100"]
        chosen = [man["installers"][1], man["dlcs"][0]]        # PL installer + DLC 1001
        self.assertTrue(app._archive_download_worker(self.w.games[0], chosen))
        rec = self.arc().read_record("100", "B1")
        # the archive takes the whole build: every language and every owned DLC, not only the chosen rows
        self.assertEqual((rec["state"], rec["scope"]["languages"], rec["scope"]["dlcs"]),
                         (DA.STATE_COMPLETE, ["en", "pl"], ["1001", "1002"]))
        self.assertEqual([p.name for p in self.folder("alpha").glob("*.exe")], [])
        self.assertFalse(any(app.GOG_GAMES.iterdir()))       # nothing installed / unpacked

    def test_missing_dependency_keeps_installers(self):
        self.w.add_game("100", "alpha", deps=())
        self.w.metas["100"]["dependencies"] = ["DOSBox"]               # not in the repository
        self.assertFalse(app._archive_all_worker())
        self.assertEqual(len(self.installers("alpha")), 5)

    def test_dependency_is_archived(self):
        self.w.add_game("100", "alpha", deps=("MSVC",))
        self.assertTrue(app._archive_all_worker())
        rec = self.arc().read_record("100", "B1")
        self.assertEqual([d["id"] for d in rec["dependencies"]], ["MSVC"])

    def test_version_change_is_reported(self):
        self.w.add_game("100", "alpha", version="1.0", build_version="1.1")
        app._archive_all_worker()
        rep = next(m for m in self.sent if m.get("type") == "migration_report")["report"]
        self.assertIn("1.0 → depot 1.1", rep["migrated"][0]["version_change"])

    def test_archive_contains_no_secrets(self):
        self.w.add_game("100", "alpha")
        app._archive_all_worker()
        for p in self.arc().root.rglob("*.json"):
            txt = p.read_text(encoding="utf-8")
            self.assertNotIn("SECRET-TOKEN", txt)
            self.assertNotIn("sec://", txt)


class InstallFromArchive(ArchiveTestBase):
    def setUp(self):
        super().setUp()
        self.w.add_game("100", "alpha", disk_langs=("en", "pl"), deps=("MSVC",))
        self.assertTrue(app._archive_all_worker())
        self.fetched.clear()

    def _block_network(self):
        import urllib.request

        def no_net(*a, **k):
            raise AssertionError("sieć zablokowana w teście")
        self._urlopen = urllib.request.urlopen
        urllib.request.urlopen = no_net
        app._fetch_chunk_raw = no_net
        app._cdn_depot_manifest = no_net
        app._pick_build = no_net
        self.addCleanup(lambda: setattr(urllib.request, "urlopen", self._urlopen))

    def test_install_offline_multilang_dlc_deps(self):
        self._block_network()
        ok = app._archive_install_worker("100", None, ["pl", "en"], ["1001", "1002"])
        self.assertTrue(ok)
        d = app.GOG_GAMES / "alpha dir"
        self.assertEqual((d / "bin/game.exe").read_bytes(), b"GAME-100-B1")
        self.assertEqual((d / "data/shared.dat").read_bytes(), SHARED)   # neutral data
        self.assertEqual((d / "sfc/b.txt").read_bytes(), b"bbbb")
        self.assertTrue((d / "lang/pl.txt").exists() and (d / "lang/en.txt").exists())
        info = json.loads((d / "goggame-100.info").read_text())
        self.assertEqual(info["language"], "pl")                        # primary language wins
        self.assertEqual((d / "dlc/1001.pak").read_bytes(), b"DLC-1001")
        self.assertTrue((d / "goggame-1002.info").exists())             # DLC without files
        self.assertTrue((d / "__redist/MSVC/MSVC.exe").exists())        # dependency
        self.assertFalse((d / app._DEPOT_STATE_NAME).exists())
        self.assertEqual(app.scan_installed_games().get("100"), str(d))

    def test_install_single_language_gets_neutral_only_plus_that_language(self):
        self.assertTrue(app._archive_install_worker("100", None, ["en"], []))
        d = app.GOG_GAMES / "alpha dir"
        self.assertTrue((d / "data/shared.dat").exists())
        self.assertFalse((d / "lang/pl.txt").exists())
        self.assertEqual(json.loads((d / "goggame-100.info").read_text())["language"], "en")
        self.assertFalse((d / "dlc").exists())

    def test_language_outside_scope_is_reported_not_downloaded(self):
        chk = app.check_archive_install("100", None, ["de"], [])
        self.assertFalse(chk["complete"])
        self.assertIn("język de", chk["gaps"])
        self.assertFalse(app._archive_install_worker("100", None, ["de"], []))
        self.assertEqual(self.fetched, [])                              # no silent CDN fallback

    def test_missing_chunk(self):
        arc = self.arc()
        md5 = hashlib.md5(zlib.compress(b"GAME-100-B1")).hexdigest()
        arc.chunk_path(md5).unlink()
        chk = app.check_archive_install("100", None, ["en"], [])
        self.assertEqual(chk["missing_chunks"], 1)
        self.assertFalse(chk["complete"])
        self.assertFalse(app._archive_install_worker("100", None, ["en"], []))
        self.assertEqual(self.fetched, [])
        self.assertTrue(app._archive_repair_worker("100", None, ["en"], []))   # explicit consent
        self.assertEqual(self.fetched, [md5])
        self.assertTrue(app._archive_install_worker("100", None, ["en"], []))

    def test_corrupt_chunk_detected_and_repaired(self):
        arc = self.arc()
        md5 = hashlib.md5(zlib.compress(b"GAME-100-B1")).hexdigest()
        p = arc.chunk_path(md5)
        p.write_bytes(b"X" * p.stat().st_size)                          # same size, bad bytes
        self.assertEqual(app.check_archive_install("100", None, ["en"], [], deep=True)["corrupt_chunks"], 1)
        self.assertFalse(app._archive_install_worker("100", None, ["en"], []))
        self.assertTrue(app._archive_repair_worker("100", None, ["en"], []))
        self.assertTrue(app._archive_install_worker("100", None, ["en"], []))

    def test_resume_install_after_crash(self):
        orig = DA.DepotArchive.read_chunk_plain
        n = {"k": 0}

        def crashy(self_, md5, plain_md5=None):
            n["k"] += 1
            if n["k"] == 3:
                raise _Crash()
            return orig(self_, md5, plain_md5)
        DA.DepotArchive.read_chunk_plain = crashy
        app.get_download_threads_orig = app.get_download_threads
        app.get_download_threads = lambda: 1
        try:
            with self.assertRaises(_Crash):
                app._archive_install_worker("100", None, ["en"], [])
            d = app.GOG_GAMES / "alpha dir"
            self.assertTrue((d / app._DEPOT_STATE_NAME).exists())
            self.assertEqual(app.scan_installed_games(), {})            # not "installed" yet
            DA.DepotArchive.read_chunk_plain = orig
            reads = []
            DA.DepotArchive.read_chunk_plain = lambda s, m, pm=None: reads.append(m) or orig(s, m, pm)
            self.assertTrue(app._archive_install_worker("100", None, ["en"], []))
            self.assertNotIn(hashlib.md5(zlib.compress(b"GAME-100-B1")).hexdigest(), reads)
        finally:
            DA.DepotArchive.read_chunk_plain = orig
            app.get_download_threads = app.get_download_threads_orig

    def test_add_dlc_to_existing_install(self):
        self.assertTrue(app._archive_install_worker("100", None, ["en"], []))
        d = app.GOG_GAMES / "alpha dir"
        self.assertFalse((d / "dlc/1001.pak").exists())
        self.assertTrue(app._archive_install_worker("100", None, ["en"], ["1001"], dlc_only=True))
        self.assertTrue((d / "dlc/1001.pak").exists())
        self.assertEqual(app._installed_dlc_ids(str(d), "100"), ["1001"])

    def test_dlc_refused_for_other_build(self):
        self.assertTrue(app._archive_install_worker("100", None, ["en"], []))
        d = app.GOG_GAMES / "alpha dir"
        info = json.loads((d / "goggame-100.info").read_text())
        info["buildId"] = "OTHER"
        (d / "goggame-100.info").write_text(json.dumps(info))
        self.assertFalse(app._archive_install_worker("100", None, ["en"], ["1001"], dlc_only=True))
        self.assertFalse((d / "dlc/1001.pak").exists())

    def test_custom_target_directory(self):
        target = app.GOG_GAMES / "Custom"
        self.assertTrue(app._archive_install_worker("100", None, ["en"], [], str(target)))
        self.assertTrue((target / "bin/game.exe").exists())

    def test_path_traversal_in_manifest_is_refused(self):
        arc = self.arc()
        mid = "100nB1"
        man = arc.get_manifest("depot", mid)
        man["depot"]["items"].append(_file("..\\..\\evil.txt", b"pwn", self.w.cdn))
        arc.put_manifest("depot", mid, man)
        arc.put_chunk(man["depot"]["items"][-1]["chunks"][0]["compressedMd5"],
                      self.w.cdn[man["depot"]["items"][-1]["chunks"][0]["compressedMd5"]])
        self.assertFalse(app._archive_install_worker("100", None, ["en"], []))
        self.assertFalse((app.GOG_GAMES.parent / "evil.txt").exists())
        self.assertFalse((app.GOG_GAMES / "evil.txt").exists())


class PathSafety(unittest.TestCase):
    def test_safe_rel(self):
        self.assertEqual(DA.safe_rel("\\a\\b.txt"), "a/b.txt")
        self.assertEqual(DA.safe_rel("a/./b"), "a/b")
        self.assertEqual(DA.safe_rel("/etc/passwd"), "etc/passwd")   # root-relative → inside
        for bad in ("../x", "a/../../x", "C:\\Windows\\x", "\\\\srv\\s",
                    "a/CON", "a/nul.txt", "file.txt:stream", "", "a\x00b"):
            with self.assertRaises(DA.UnsafePath, msg=bad):
                DA.safe_rel(bad)

    def test_safe_join_stays_inside(self):
        with tempfile.TemporaryDirectory() as d:
            p = DA.safe_join(Path(d), "x/y.txt")
            self.assertTrue(str(p.resolve()).startswith(str(Path(d).resolve())))

    def test_fileset_refuses_whole_batch_on_unsafe_path(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "game"
            root.mkdir()
            errs = app._download_depot_fileset(
                [{"path": "ok.txt", "chunks": []}, {"path": "..\\out.txt", "chunks": []}],
                [], None, None, root, 1, lambda n: None, fetch=lambda c: b"")
            self.assertEqual(len(errs), 1)
            self.assertFalse((root / "ok.txt").exists())        # nothing written at all
            self.assertFalse((Path(d) / "out.txt").exists())


class SharedObjects(unittest.TestCase):
    def test_gc_keeps_chunks_shared_with_other_records(self):
        with tempfile.TemporaryDirectory() as d:
            arc = DA.DepotArchive(Path(d))
            arc.ensure()
            cdn = {}
            shared = _file("s.dat", SHARED, cdn)
            only_old = _file("old.dat", b"old-only", cdn)
            only_b = _file("b.dat", b"game-b", cdn)
            arc.put_manifest("depot", "mold", {"depot": {"items": [shared, only_old]}})
            arc.put_manifest("depot", "mbbb", {"depot": {"items": [shared, only_b]}})
            for m, data in cdn.items():
                arc.put_chunk(m, data)
            arc.write_record({"product_id": "1", "build_id": "OLD", "depots": [{"manifest": "mold"}],
                              "state": "complete"})
            arc.write_record({"product_id": "2", "build_id": "B", "depots": [{"manifest": "mbbb"}],
                              "state": "complete"})
            arc.remove_record("1", "OLD")
            n, _ = arc.gc()
            self.assertEqual(n, 1)
            self.assertTrue(arc.has_chunk(shared["chunks"][0]["compressedMd5"]))
            self.assertTrue(arc.has_chunk(only_b["chunks"][0]["compressedMd5"]))
            self.assertFalse(arc.has_chunk(only_old["chunks"][0]["compressedMd5"]))

    def test_new_build_prunes_old_but_keeps_shared(self):
        t = ArchiveTestBase("run")
        # integration: archive B1, then GOG publishes B2 → B1 record gone, shared chunk kept
        t.setUp()
        try:
            t.w.add_game("100", "alpha")
            app._archive_all_worker()
            t.w.add_game("100", "alpha", build_id="B2", installers=False)
            t.w.games = t.w.games[:1]
            app._archive_all_worker()
            arc = app._archive()
            self.assertIsNone(arc.read_record("100", "B1"))
            self.assertEqual(arc.read_record("100", "B2")["state"], DA.STATE_COMPLETE)
            self.assertTrue(arc.has_chunk(hashlib.md5(zlib.compress(SHARED)).hexdigest()))
            self.assertFalse(arc.has_chunk(hashlib.md5(zlib.compress(b"GAME-100-B1")).hexdigest()))
        finally:
            t.tearDown()


class Format(unittest.TestCase):
    def test_marker_and_newer_version_refused(self):
        with tempfile.TemporaryDirectory() as d:
            arc = DA.DepotArchive(Path(d))
            arc.ensure()
            m = json.loads((Path(d) / "archive.json").read_text())
            self.assertEqual((m["format"], m["version"]), (DA.FORMAT, DA.VERSION))
            m["version"] = DA.VERSION + 1
            (Path(d) / "archive.json").write_text(json.dumps(m))
            with self.assertRaises(DA.ArchiveError):
                arc.ensure()

    def test_put_chunk_rejects_wrong_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            arc = DA.DepotArchive(Path(d))
            with self.assertRaises(DA.CorruptChunk):
                arc.put_chunk("0" * 32, b"not matching")

    def test_strip_secrets(self):
        self.assertEqual(DA.strip_secrets({"a": 1, "access_token": "x", "n": [{"Cookie": 1, "b": 2}]}),
                         {"a": 1, "n": [{"b": 2}]})


if __name__ == "__main__":
    unittest.main()


class FullScope(ArchiveTestBase):
    def test_dlc_not_owned_is_not_archived(self):
        self.w.add_game("100", "alpha", installers=False)
        self.owned = {"100", "1001"}                         # 1002 is in the build but not owned
        man = self.w.dl_manifests["100"]
        self.assertTrue(app._archive_download_worker(self.w.games[0], [man["installers"][0]]))
        rec = self.arc().read_record("100", "B1")
        self.assertEqual(rec["scope"]["dlcs"], ["1001"])

    def test_owned_list_unavailable_keeps_dlc_from_installers(self):
        self.w.add_game("100", "alpha", installers=False)
        self.owned = set()
        app._owned_ids_cached = lambda max_age=1800: None    # account call failed
        man = self.w.dl_manifests["100"]
        self.assertTrue(app._archive_download_worker(self.w.games[0], [man["installers"][0], man["dlcs"][0]]))
        rec = self.arc().read_record("100", "B1")
        self.assertEqual((rec["scope"]["languages"], rec["scope"]["dlcs"]), (["en", "pl"], ["1001"]))

    def test_update_all_extends_old_partial_record(self):
        """an archive from before (EN only, no DLC): Aktualizuj wszystkie adds the missing language and DLC,
        downloading only chunks that are not in the archive yet"""
        self.w.add_game("100", "alpha", installers=False)
        self.owned = {"100"}
        man = self.w.dl_manifests["100"]
        app._owned_ids_cached = lambda max_age=1800: {"100"}
        orig = app._build_lang_set
        app._build_lang_set = lambda meta, pid: {"en"}       # behave like the old, partial scope
        try:
            self.assertTrue(app._archive_download_worker(self.w.games[0], [man["installers"][0]]))
        finally:
            app._build_lang_set = orig
        rec = self.arc().read_record("100", "B1")
        self.assertEqual((rec["scope"]["languages"], rec["scope"]["dlcs"]), (["en"], []))
        first = list(self.fetched)
        self.fetched.clear()
        app._owned_ids_cached = lambda max_age=1800: {"100", "1001", "1002"}
        self.assertTrue(app._archive_all_worker())
        rec = self.arc().read_record("100", "B1")
        self.assertEqual((rec["state"], rec["scope"]["languages"], rec["scope"]["dlcs"]),
                         (DA.STATE_COMPLETE, ["en", "pl"], ["1001", "1002"]))
        self.assertTrue(self.fetched and not set(self.fetched) & set(first))   # only new chunks


class MetaExport(ArchiveTestBase):
    V2 = {"_links": {"boxArtImage": {"href": "https://img/box.jpg"}, "logo": {"href": "https://img/logo.png"},
                     "galaxyBackgroundImage": {"href": "https://img/bg.jpg"}, "iconSquare": {"href": "https://img/sq.png"}},
          "_embedded": {"product": {"id": 100, "title": "Alpha", "globalReleaseDate": "2001-02-03T00:00:00+02:00"},
                        "developers": [{"name": "Dev"}], "publishers": [{"name": "Pub"}], "tags": [{"name": "RPG"}]}}

    def game(self, slug="alpha"):
        return {"id": "100", "slug": slug, "title": "Alpha",
                "product": {"id": 100, "slug": slug, "title": "Alpha", "description": {"lead": "Opis"},
                            "images": {"icon": "//img/icon.png", "logo2x": "//img/glx.jpg"}},
                "details": {"title": "Alpha", "cdKey": "AAAA-BBBB", "cdKeys": [{"key": "X"}], "changelog": "c",
                            "downloads": [["English", {"windows": [{"manualUrl": "/downlink/x"}]}]]}}

    def test_folder_gets_json_and_images_without_keys(self):
        got = []
        r = app.export_game_meta(self.game(), fetch_v2=lambda pid: self.V2,
                                 fetch_image=lambda url: got.append(url) or b"IMG")
        d = app.BASE / "alpha"
        self.assertEqual(json.loads((d / "product_alpha.json").read_text(encoding="utf-8"))["description"]["lead"], "Opis")
        det = (d / "game-details.json").read_text(encoding="utf-8")
        self.assertNotIn("AAAA", det)
        self.assertNotIn("cdKeys", det)
        self.assertNotIn("downlink", det)
        gal = json.loads((d / "galaxy_alpha.json").read_text(encoding="utf-8"))
        self.assertEqual((gal["developers"], gal["publishers"], gal["tags"]), (["Dev"], ["Pub"], ["RPG"]))
        for n in ("icon_alpha.png", "logo_alpha.jpg", "boxart_alpha.jpg", "background_alpha.jpg",
                  "titlelogo_alpha.png", "iconsquare_alpha.png"):
            self.assertEqual((d / n).read_bytes(), b"IMG", n)
        self.assertEqual(r["images"], 6)
        # second run: images that exist are not downloaded again, unchanged JSON is not rewritten
        got.clear()
        r2 = app.export_game_meta(self.game(), fetch_v2=lambda pid: self.V2, fetch_image=lambda url: got.append(url) or b"IMG")
        self.assertEqual((got, r2["json"], r2["images"]), ([], 0, 0))

    def test_unsafe_slug_is_skipped(self):
        r = app.export_game_meta(self.game("../evil"), fetch_v2=lambda pid: self.V2, fetch_image=lambda url: b"x")
        self.assertTrue(r["errors"])
        self.assertFalse((app.BASE.parent / "evil").exists())

    def test_migration_writes_metadata_next_to_installers(self):
        self.w.add_game("100", "alpha")
        app._fetch_v2_game = lambda pid: self.V2
        app._fetch_image = lambda url: b"IMG"
        app._archive_all_worker()
        self.assertTrue((self.folder("alpha") / "product_alpha.json").exists())
        self.assertTrue((self.folder("alpha") / "boxart_alpha.jpg").exists())


# ══════════════════════════════════════════════════════════════════════════════

class _FakeRange:
    def __init__(self, data: bytes):
        import io
        self.status, self._b = 206, io.BytesIO(data)

    def read(self, n=-1):
        return self._b.read(min(n, 7) if n and n > 0 else n)     # short reads, like a socket

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class V1Base(ArchiveTestBase):
    """A game with only a Galaxy generation-1 build: repository.json + depot manifests + one main.bin per
    product, plus two redists (one with a targetDir). No tests here — subclasses share the world."""
    PID, TS = "300", "26557639"

    def setUp(self):
        super().setUp()
        w, pid, ts = self.w, self.PID, self.TS
        big = bytes(range(256)) * 9000                      # > 2 chunks of 1 MiB
        self.files = {"/SAVE/ANTARA.SCF": b"SAVE", "/RDATA/A.WDB": b"A" * 50, "/game.exe": b"EXE-v1",
                      "/data/big.dat": big, "/empty.txt": b""}
        blob, entries = bytearray(), []
        for path, data in self.files.items():
            blob += b"\x00" * 13                              # gaps between files, as in real main.bin
            entries.append({"offset": len(blob), "size": len(data), "path": path,
                            "hash": hashlib.md5(data).hexdigest(), "url": f"{pid}/main.bin"})
            blob += data
        entries.append({"path": "/SAVE", "directory": True})
        entries.append({"path": "/SAVE/dummy.txt", "size": 0})       # real v1: empty file, no offset/url
        self.files["/SAVE/dummy.txt"] = b""
        sup = b"SUPPORT-EXE"
        entries_neutral = [{"offset": len(blob), "size": len(sup), "support": True,
                            "path": f"{pid}/galaxy_support.exe", "hash": hashlib.md5(sup).hexdigest(),
                            "url": f"{pid}/main.bin"}]
        blob += sup
        self.blob = bytes(blob)
        base = f"v1cdn/{pid}/windows/{ts}"
        self.v1 = {
            f"{base}/repository.json": {"product": {
                "timestamp": int(ts), "installDirectory": "Antara", "rootGameID": pid,
                "gameIDs": [{"gameID": pid, "name": {"en": "Antara"}, "dependencies": []}],
                "depots": [
                    {"languages": ["Neutral"], "size": str(len(sup)), "gameIDs": [pid],
                     "systems": ["Windows"], "manifest": "neutral-uuid.json"},
                    {"languages": ["English"], "size": str(sum(map(len, self.files.values()))),
                     "gameIDs": [pid], "systems": ["Windows"], "manifest": "english-uuid.json"},
                    {"languages": ["English"], "size": "5", "gameIDs": [pid], "systems": ["Mac"],
                     "manifest": "mac-uuid.json"},
                    {"redist": "DOSBox074", "size": "0", "targetDir": "DOSBOX"},
                    {"redist": "nGlide_103", "size": "0", "targetDir": "system/"}]}},
            f"{base}/neutral-uuid.json": {"version": 1, "depot": {"files": entries_neutral}},
            f"{base}/english-uuid.json": {"version": 1, "depot": {"files": entries}},
        }
        w.add_game(pid, "antara", langs=("en",), dlc_files=False, dlc_meta=False)
        w.deps["DOSBox074"] = ("dosbox00", {"depot": {"items": [_file("DOSBOX\\DOSBox.exe", b"DOSBOX", w.cdn)]}})
        w.deps["nGlide_103"] = ("nglide00", {"depot": {"items": [_file("\\glide.dll", b"GLIDE", w.cdn)]}})
        w.builds[pid] = {"build_id": "9121", "generation": 1, "legacy_build_id": int(ts),
                         "version_name": "", "link": f"https://{base}/repository.json"}
        orig_meta = app._cs_get_zlib
        self.v1_gets = []

        def cs(url):
            key = url.split("://", 1)[1]
            if key in self.v1:
                self.v1_gets.append(key)
                return json.loads(json.dumps(self.v1[key]))
            return orig_meta(url)
        app._cs_get_zlib = cs
        self.ranges = []
        app._authed_json = lambda url, box: {"urls": [{"endpoint_name": "fastly", "url_format": "blob://{path}",
                                                       "parameters": {"path": f"/windows/{ts}/"}}]}

        def rng(url, start, length):
            import urllib.error
            if url != f"blob:///windows/{ts}/{pid}/main.bin":   # only the second candidate path exists
                raise urllib.error.HTTPError(url, 404, "nf", {}, None)
            self.ranges.append((start, length))
            return _FakeRange(self.blob[start:start + length])
        for k in ("_authed_json", "_v1_open"):
            self._orig.setdefault(k, getattr(app, k))
        app._v1_open = rng


class V1Build(V1Base):
    def test_v1_build_archived_as_v2_chunks_and_installs_offline(self):
        self.assertTrue(app._archive_all_worker())
        rec = self.arc().read_record(self.PID, "9121")
        self.assertEqual(rec["state"], DA.STATE_COMPLETE)
        self.assertEqual(rec["generation"], 2)                      # archive format
        self.assertEqual(rec["source"], {"content_system": 1, "timestamp": self.TS})
        self.assertEqual(rec["scope"]["languages"], ["en"])
        self.assertEqual(len(rec["depots"]), 2)                     # Mac depot left out
        for d in rec["depots"]:
            self.assertRegex(d["manifest"], r"^[0-9a-f]{32}$")
        # every chunk is a real zlib chunk named by its compressed MD5, plain MD5 and size match
        for c in self.arc().record_chunks(rec):
            comp = self.arc().read_chunk(c["compressedMd5"])
            self.assertEqual(hashlib.md5(zlib.decompress(comp, 15)).hexdigest(), c["md5"])
            self.assertLessEqual(c["size"], app.V1_CHUNK)
        # small neighbouring files share one Range request; nothing was fetched from the v2 chunk CDN
        self.assertLess(len(self.ranges), len(self.files))
        dep_chunks = {c["compressedMd5"] for _mid, man in self.w.deps.values() for c in DA.manifest_chunks(man)}
        self.assertLessEqual(set(self.fetched), dep_chunks)        # game files never from the v2 chunk CDN
        self.assertEqual(self.arc().read_journal(self.PID)["phase"], DA.PH_DONE)

        app._v1_open = app._cs_get_zlib = app._pick_build = lambda *a: (_ for _ in ()).throw(
            AssertionError("sieć zablokowana w teście"))
        self.assertTrue(app._archive_install_worker(self.PID, None, ["en"], []))
        d = app.GOG_GAMES / "Antara"
        for path, data in self.files.items():
            self.assertEqual((d / path.lstrip("/")).read_bytes(), data, path)
        self.assertEqual((d / "galaxy_support.exe").read_bytes(), b"SUPPORT-EXE")   # no product folder
        self.assertEqual((d / "DOSBOX/DOSBox.exe").read_bytes(), b"DOSBOX")        # already under targetDir
        self.assertEqual((d / "system/glide.dll").read_bytes(), b"GLIDE")          # moved to targetDir
        self.assertFalse((d / "glide.dll").exists())

    def test_second_run_downloads_nothing(self):
        self.assertTrue(app._archive_all_worker())
        self.ranges.clear()
        self.assertTrue(app._archive_all_worker())
        self.assertEqual(self.ranges, [])

    def test_md5_mismatch_keeps_record_incomplete_and_installers(self):
        self.blob = self.blob.replace(b"EXE-v1", b"EXE-v2")
        before = self.installers("antara")
        self.assertFalse(app._archive_all_worker())
        self.assertEqual(self.installers("antara"), before)
        self.assertIsNone(self.arc().read_record(self.PID, "9121"))
        j = self.arc().read_journal(self.PID)
        self.assertEqual(j["phase"], "failed")
        self.assertIn("MD5", j["error"])


class SkipJournal(ArchiveTestBase):
    def test_skipped_game_journal_records_reason(self):
        self.w.add_game("100", "alpha")
        app._pick_build = lambda pid: (_ for _ in ()).throw(RuntimeError("brak buildów"))
        app._archive_all_worker()
        j = self.arc().read_journal("100")
        self.assertEqual(j["phase"], DA.PH_SKIPPED)
        self.assertIn("brak buildów", j["error"])


class V1Repair(V1Base):
    def test_repair_rebuilds_lost_v1_chunks_from_main_bin(self):
        self.assertTrue(app._archive_all_worker())
        rec = self.arc().read_record(self.PID, "9121")
        man = next(self.arc().get_manifest("depot", d["manifest"]) for d in rec["depots"]
                   if d["languages"] == ["en"])
        exe = next(i for i in man["depot"]["items"] if i.get("path") == "game.exe")
        lost = exe["chunks"][0]["compressedMd5"]
        self.arc().chunk_path(lost).unlink()
        self.ranges.clear()
        self.fetched.clear()
        self.assertTrue(app._archive_repair_worker(self.PID, "9121"))
        self.assertTrue(self.arc().has_chunk(lost))
        self.assertEqual([n for _s, n in self.ranges if n > 1], [len(b"EXE-v1")])   # only the damaged file
        self.assertFalse(self.fetched)                     # never from the v2 chunk CDN
        self.assertTrue(app._archive_install_worker(self.PID, None, ["en"], []))

    def test_same_size_corrupt_chunk_is_not_trusted(self):
        """a chunk file left from an aborted run with the right size but wrong bytes is read by the verify
        pass (not taken as checked): the record is not committed over it"""
        data = self.files["/game.exe"]
        comp = zlib.compress(data, 6)
        arc = self.arc()
        arc.ensure()
        p = arc.chunk_path(hashlib.md5(comp).hexdigest())
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"X" * len(comp))
        self.assertFalse(app._archive_all_worker())
        self.assertEqual(arc.read_record(self.PID, "9121")["state"], DA.STATE_INCOMPLETE)
        self.assertTrue(app._archive_all_worker())          # the bad copy was dropped → refetched
        self.assertEqual(arc.read_record(self.PID, "9121")["state"], DA.STATE_COMPLETE)

    def test_done_journal_is_not_relabelled_by_a_later_skip(self):
        self.assertTrue(app._archive_all_worker())
        arc = self.arc()
        app._journal_mark(arc, self.PID, DA.PH_SKIPPED, "x")
        self.assertEqual(arc.read_journal(self.PID)["phase"], DA.PH_DONE)


class ScopeGrowthKeepsComplete(ArchiveTestBase):
    def test_failed_scope_extension_keeps_the_complete_record(self):
        self.w.add_game("100", "alpha", langs=("en",))
        self.assertTrue(app._archive_all_worker())
        self.assertEqual(self.arc().read_record("100", "B1")["scope"]["languages"], ["en"])
        # the same build gains a German depot; its download fails
        cdn, mid = self.w.cdn, "100deB1"
        self.w.manifests[mid] = {"depot": {"items": [_file("lang\de.txt", b"de-100", cdn)]}}
        self.w.metas["100"]["depots"].append({"productId": "100", "languages": ["de-DE"], "manifest": mid})
        bad = DA.manifest_chunks(self.w.manifests[mid])[0]["compressedMd5"]

        def fail(md5):
            if md5 == bad:
                raise RuntimeError("[WinError 1392] uszkodzony")
        self.fail_fetch = fail
        self.assertFalse(app._archive_all_worker())
        rec = self.arc().read_record("100", "B1")
        self.assertEqual(rec["state"], DA.STATE_COMPLETE)            # still published
        self.assertEqual(rec["scope"]["languages"], ["en"])
        self.fail_fetch = None
        self.assertTrue(app._archive_all_worker())
        self.assertEqual(self.arc().read_record("100", "B1")["scope"]["languages"], ["de", "en"])


class V1FailedRepair(V1Base):
    def test_failed_repair_does_not_leave_a_complete_record_with_lost_chunks(self):
        self.assertTrue(app._archive_all_worker())
        rec = self.arc().read_record(self.PID, "9121")
        self.arc().chunk_path(self.arc().record_chunks(rec)[0]["compressedMd5"]).unlink()

        def down(*a):
            raise RuntimeError("CDN niedostępny")
        app._v1_open = down
        self.assertFalse(app._archive_repair_worker(self.PID, "9121"))
        self.assertEqual(self.arc().read_record(self.PID, "9121")["state"], DA.STATE_INCOMPLETE)


# ══════════════════════════════════════════════════════════════════════════════
# Update plan: depot_archive.diff_manifests (pure — no network, no archive writes)

def _c(tag: str, size: int = 100) -> dict:
    """Synthetic chunk: compressedMd5 derived from `tag`, compressedSize = size."""
    return {"compressedMd5": hashlib.md5(tag.encode()).hexdigest(), "compressedSize": size,
            "md5": hashlib.md5(b"p" + tag.encode()).hexdigest(), "size": size * 2}


def _f(path: str, *tags, md5="auto", size=100) -> dict:
    it = {"type": "DepotFile", "path": path, "chunks": [_c(t, size) for t in tags]}
    if md5 == "auto":
        it["md5"] = hashlib.md5(("|".join(tags)).encode()).hexdigest()
    elif md5:
        it["md5"] = md5
    return it


def _m(*items, sfc=None) -> dict:
    dep = {"items": list(items)}
    if sfc is not None:
        dep["smallFilesContainer"] = {"chunks": [_c(t) for t in sfc]}
    return {"depot": dep}


def _paths(lst):
    return [e["path"] for e in lst]


class DiffManifests(unittest.TestCase):
    def test_unchanged_file(self):
        old = _m(_f("bin\\game.exe", "a", "b"))
        r = DA.diff_manifests(old, _m(_f("bin\\game.exe", "a", "b")))
        self.assertEqual(r["counts"], {"added": 0, "changed": 0, "removed": 0, "unchanged": 1})
        self.assertEqual(r["total_download_bytes"], 0)
        self.assertEqual(r["unchanged"][0]["chunks"], 2)

    def test_path_key_is_normalised_and_case_insensitive(self):
        r = DA.diff_manifests(_m(_f("Bin\\Game.EXE", "a")), _m(_f("/bin/game.exe", "a")))
        self.assertEqual(r["counts"]["unchanged"], 1)
        self.assertEqual(r["counts"]["added"] + r["counts"]["removed"], 0)

    def test_partially_changed_file(self):
        r = DA.diff_manifests(_m(_f("data.pak", "a", "b", "c")), _m(_f("data.pak", "a", "X", "c")))
        ch = r["changed"][0]
        self.assertEqual((ch["chunks"], ch["reused_chunks"], ch["missing_chunks"], ch["missing_bytes"]),
                         (3, 2, 1, 100))
        self.assertIn("chunks", ch["reasons"])
        self.assertNotIn("layout_changed", ch)
        self.assertEqual(r["total_download_bytes"], 100)
        self.assertEqual(r["reused_bytes"], 200)

    def test_added_file(self):
        r = DA.diff_manifests(_m(_f("a.txt", "a")), _m(_f("a.txt", "a"), _f("new.dat", "n1", "n2")))
        self.assertEqual(_paths(r["added"]), ["new.dat"])
        self.assertEqual(r["added"][0]["missing_chunks"], 2)
        self.assertEqual(r["total_download_bytes"], 200)

    def test_removed_file(self):
        r = DA.diff_manifests(_m(_f("a.txt", "a"), _f("old.dat", "o")), _m(_f("a.txt", "a")))
        self.assertEqual(_paths(r["removed"]), ["old.dat"])
        self.assertEqual(r["removed"][0]["chunks"], 1)
        self.assertEqual(r["total_download_bytes"], 0)

    def test_only_chunk_order_changed(self):
        r = DA.diff_manifests(_m(_f("x.bin", "a", "b", md5="m")), _m(_f("x.bin", "b", "a", md5="m")))
        ch = r["changed"][0]
        self.assertTrue(ch["layout_changed"])
        self.assertEqual((ch["missing_chunks"], ch["missing_bytes"]), (0, 0))
        self.assertEqual(r["total_download_bytes"], 0)

    def test_empty_manifests(self):
        r = DA.diff_manifests({}, _m(_f("a", "a")))
        self.assertEqual(r["counts"]["added"], 1)
        self.assertFalse(r["old_missing"])
        r = DA.diff_manifests({"depot": {"items": []}}, {"depot": {"items": []}})
        self.assertEqual(r["counts"], {"added": 0, "changed": 0, "removed": 0, "unchanged": 0})
        self.assertEqual(r["total_download_bytes"], 0)

    def test_missing_manifest(self):
        r = DA.diff_manifests(None, _m(_f("a", "a")))
        self.assertTrue(r["old_missing"])
        self.assertEqual(_paths(r["added"]), ["a"])
        with self.assertRaises(DA.ArchiveError):
            DA.diff_manifests(_m(_f("a", "a")), None)

    def test_chunk_shared_by_several_files_downloads_once(self):
        r = DA.diff_manifests(None, _m(_f("one.dat", "S"), _f("two.dat", "S"), _f("three.dat", "S", "T")))
        self.assertEqual(sum(e["missing_bytes"] for e in r["added"]), 400)   # per file: each time
        self.assertEqual(r["total_download_bytes"], 200)                      # globally: S and T once
        self.assertEqual(r["download_chunks"], 2)

    def test_md5_missing_on_one_or_both_sides_is_not_a_mismatch(self):
        for old_md5, new_md5 in ((None, None), ("abc", None), (None, "abc")):
            r = DA.diff_manifests(_m(_f("f", "a", md5=old_md5)), _m(_f("f", "a", md5=new_md5)))
            self.assertEqual(r["counts"]["unchanged"], 1, (old_md5, new_md5))
        r = DA.diff_manifests(_m(_f("f", "a", md5="abc")), _m(_f("f", "a", md5="def")))
        self.assertEqual(r["changed"][0]["reasons"], ["md5"])

    def test_have_sees_chunk_from_another_game(self):
        other_game = {_c("FROM-OTHER")["compressedMd5"], _c("a")["compressedMd5"]}
        new = _m(_f("data.pak", "a", "FROM-OTHER"))
        r = DA.diff_manifests(_m(_f("data.pak", "a")), new, have=other_game.__contains__)
        ch = r["changed"][0]
        self.assertEqual((ch["reused_chunks"], ch["missing_chunks"]), (2, 0))
        self.assertEqual(r["total_download_bytes"], 0)
        r = DA.diff_manifests(_m(_f("data.pak", "a")), new)           # default: old manifest only
        self.assertEqual(r["changed"][0]["missing_chunks"], 1)

    def test_sfc_container_changed_downloads_whole_container(self):
        a = {"type": "DepotFile", "path": "sfc\\a.txt", "sfcRef": {"offset": 0, "size": 4}, "md5": "m-a"}
        b = {"type": "DepotFile", "path": "sfc\\b.txt", "sfcRef": {"offset": 4, "size": 4}, "md5": "m-b"}
        r = DA.diff_manifests(_m(dict(a), dict(b), sfc=["s1", "s2"]),
                              _m(dict(a), dict(b), sfc=["s1", "s3"]))   # same file MD5s, new container
        self.assertEqual(r["sfc"]["state"], "changed")
        self.assertEqual((r["sfc"]["reused_chunks"], r["sfc"]["missing_chunks"]), (1, 1))
        self.assertEqual(r["total_download_bytes"], 100)
        self.assertEqual(_paths(r["changed"]), ["sfc\\a.txt", "sfc\\b.txt"])
        self.assertTrue(all(e["reasons"] == ["sfc_container_changed"] for e in r["changed"]))
        self.assertFalse(r["issues"])

    def test_sfc_same_container_but_sfcref_changed_is_inconsistent(self):
        a = {"type": "DepotFile", "path": "sfc\\a.txt", "sfcRef": {"offset": 0, "size": 4}}
        a2 = {"type": "DepotFile", "path": "sfc\\a.txt", "sfcRef": {"offset": 2, "size": 4}}
        r = DA.diff_manifests(_m(a, sfc=["s1"]), _m(a2, sfc=["s1"]))
        self.assertEqual(r["sfc"]["state"], "unchanged")
        ch = r["changed"][0]
        self.assertTrue(ch["manifest_inconsistent"])
        self.assertEqual(ch["missing_bytes"], 0)                       # no claim it can be fetched alone
        self.assertEqual(r["total_download_bytes"], 0)
        self.assertEqual(r["issues"][0]["issue"], "sfc_ref_changed_same_container")

    def test_sfc_unchanged(self):
        a = {"type": "DepotFile", "path": "s.txt", "sfcRef": {"offset": 0, "size": 4}, "md5": "x"}
        r = DA.diff_manifests(_m(dict(a), sfc=["s1"]), _m(dict(a), sfc=["s1"]))
        self.assertEqual(r["sfc"]["state"], "unchanged")
        self.assertEqual(r["counts"]["unchanged"], 1)

    def test_unchanged_file_with_chunk_lost_from_archive_is_downloaded(self):
        m = _m(_f("a.dat", "a", "b"))
        r = DA.diff_manifests(m, _m(_f("a.dat", "a", "b")), have={_c("a")["compressedMd5"]}.__contains__)
        self.assertEqual(r["counts"]["unchanged"], 1)
        self.assertEqual(r["unchanged"][0]["missing_chunks"], 1)
        self.assertEqual((r["total_download_bytes"], r["reused_bytes"]), (100, 100))
        self.assertEqual(r["issues"][0]["issue"], "chunk_missing_in_archive")

    def test_duplicate_path_reported(self):
        r = DA.diff_manifests(None, _m(_f("a", "a"), _f("A", "b")))
        self.assertEqual(r["counts"]["added"], 1)
        self.assertEqual(r["issues"][0]["issue"], "duplicate_path")

    def test_inputs_not_modified(self):
        old, new = _m(_f("a", "a")), _m(_f("a", "b"), _f("c", "c"))
        snap = json.dumps([old, new], sort_keys=True)
        DA.diff_manifests(old, new)
        DA.diff_depot_groups([(DA.depot_group_key({"productId": "1"}, "windows", 2), [old])],
                             [(DA.depot_group_key({"productId": "1"}, "windows", 2), [new])])
        self.assertEqual(json.dumps([old, new], sort_keys=True), snap)


def _key(pid="1", langs=("*",), **kw):
    return DA.depot_group_key({"productId": pid, "languages": list(langs), **kw}, "windows", 2)


class DiffDepotGroups(unittest.TestCase):
    def test_depot_added_and_removed(self):
        old = [(_key(langs=("*",)), [_m(_f("base.dat", "b"))]),
               (_key(langs=("pl-PL",)), [_m(_f("pl.txt", "p"))])]
        new = [(_key(langs=("*",)), [_m(_f("base.dat", "b"))]),
               (_key(langs=("de-DE",)), [_m(_f("de.txt", "d"))])]
        r = DA.diff_depot_groups(old, new)
        st = {tuple(g["key"]["languages"]): g["state"] for g in r["groups"]}
        self.assertEqual(st, {("*",): "unchanged", ("pl-pl",): "depot_removed", ("de-de",): "depot_added"})
        self.assertEqual(r["group_states"], {"depot_added": 1, "depot_removed": 1, "changed": 0, "unchanged": 1})
        self.assertEqual(r["counts"], {"added": 1, "changed": 0, "removed": 1, "unchanged": 1})
        self.assertEqual(r["total_download_bytes"], 100)

    def test_full_key_separates_bitness_and_gog_depot(self):
        a = _key(osBitness=["64"], isGogDepot=False)
        b = _key(osBitness=["32"], isGogDepot=False)
        r = DA.diff_depot_groups([(a, [_m(_f("x", "a"))])], [(b, [_m(_f("x", "a"))])])
        self.assertEqual(r["group_states"]["depot_added"], 1)
        self.assertEqual(r["group_states"]["depot_removed"], 1)

    def test_depots_with_same_key_are_one_group_in_any_order(self):
        m1, m2 = _m(_f("a", "a"), sfc=["s1"]), _m(_f("b", "b"), sfc=["s2"])
        r = DA.diff_depot_groups([(_key(), [m1, m2])], [(_key(), [m2, m1])])
        self.assertEqual(r["group_states"]["unchanged"], 1)
        self.assertEqual(r["groups"][0]["sfc"]["state"], "unchanged")
        self.assertEqual(r["total_download_bytes"], 0)

    def test_one_of_two_containers_changes(self):
        a = {"type": "DepotFile", "path": "a.txt", "sfcRef": {"offset": 0, "size": 4}, "md5": "ma"}
        b = {"type": "DepotFile", "path": "b.txt", "sfcRef": {"offset": 0, "size": 4}, "md5": "mb"}
        old = [(_key(), [_m(dict(a), sfc=["s1"]), _m(dict(b), sfc=["s2"])])]
        new = [(_key(), [_m(dict(a), sfc=["s1"]), _m(dict(b), sfc=["s3"])])]
        r = DA.diff_depot_groups(old, new)
        g = r["groups"][0]
        self.assertEqual([e["path"] for e in g["changed"]], ["b.txt"])     # a.txt: its container is the same
        self.assertEqual(g["changed"][0]["reasons"], ["sfc_container_changed"])
        self.assertEqual(r["total_download_bytes"], 100)

    def test_same_path_with_different_content_in_one_group_is_reported(self):
        r = DA.diff_depot_groups([], [(_key(), [_m(_f("x", "a")), _m(_f("x", "b"))])])
        self.assertEqual([i["issue"] for i in r["issues"]], ["ambiguous_path"])
        r = DA.diff_depot_groups([], [(_key(), [_m(_f("x", "a")), _m(_f("x", "a"))])])
        self.assertEqual(r["issues"], [])                                   # same content: kept once

    def test_chunk_shared_across_groups_downloads_once(self):
        new = [(_key(langs=("*",)), [_m(_f("a", "S"))]), (_key(langs=("en-US",)), [_m(_f("b", "S"))])]
        self.assertEqual(DA.diff_depot_groups([], new)["total_download_bytes"], 100)


class PlanUpdate(ArchiveTestBase):
    def setUp(self):
        super().setUp()
        self.man_calls = []
        inner = app._cdn_depot_manifest
        app._cdn_depot_manifest = lambda d: self.man_calls.append(d["manifest"]) or inner(d)

    def _status(self):
        return json.loads((app.BASE / "_depots" / "exchange" / "status.json").read_text(encoding="utf-8"))

    def _plan_file(self, pid="100"):
        return json.loads((app.BASE / "_depots" / "exchange" / "plans" / f"{pid}.json").read_text(encoding="utf-8"))

    def _archived(self, **kw):
        self.w.add_game("100", "alpha", **kw)
        self.assertTrue(app._archive_all_worker())
        self.man_calls.clear()
        self.fetched.clear()

    def _new_build(self, **kw):
        self.w.add_game("100", "alpha", build_id="B2", installers=False, **kw)
        self.w.games = self.w.games[:1]

    def test_same_build_fetches_no_manifest(self):
        self._archived()
        r = app.plan_update("100")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["plan"]["state"], "up_to_date")
        self.assertEqual(self.man_calls, [])
        self.assertEqual(self.fetched, [])
        self.assertEqual(self._status()["update_plans"]["100"]["state"], "up_to_date")
        self.assertFalse((app.BASE / "_depots" / "exchange" / "plans" / "100.json").exists())

    def test_new_build_lists_changed_file_and_downloads_nothing(self):
        self._archived()
        arc_before = sorted(p.name for p in (app.BASE / "_depots").rglob("*") if p.is_file())
        self._new_build()
        r = app.plan_update("100")
        p = r["plan"]
        self.assertEqual((p["state"], p["from_build"], p["to_build"]), ("update", "B1", "B2"))
        self.assertEqual(p["counts"]["changed"], 1)
        self.assertEqual(p["download_bytes"], len(zlib.compress(b"GAME-100-B2")))
        self.assertGreater(p["reused_bytes"], 0)
        self.assertEqual(self.fetched, [])                                   # no chunk downloaded
        self.assertTrue(self.man_calls)                                      # manifests: in memory only
        arc = self.arc()
        self.assertIsNone(arc.read_record("100", "B2"))
        self.assertFalse(any(arc.has_manifest("depot", m) for m in self.man_calls))
        arc_after = sorted(p.name for p in (app.BASE / "_depots").rglob("*")
                           if p.is_file() and "exchange" not in p.parts)
        self.assertEqual(arc_after, arc_before)
        changed = [e["path"] for g in self._plan_file()["groups"] for e in g["changed"]]
        self.assertEqual(changed, ["bin\\game.exe"])
        st = self._status()["update_plans"]["100"]
        self.assertEqual(st["files"], "plans/100.json")
        self.assertNotIn("groups_detail", st)
        self.assertNotIn("changed", st)                                      # status.json: summaries only

    def test_depot_added_and_removed_between_builds(self):
        self._archived()
        self._new_build(langs=("en", "de"))                                  # pl gone, de new
        p = app.plan_update("100")["plan"]
        self.assertEqual(p["groups"]["depot_added"], 1)
        self.assertEqual(p["groups"]["depot_removed"], 1)
        states = {tuple(g["key"].get("languages") or ()): g["state"] for g in self._plan_file()["groups"]}
        self.assertEqual(states[("de-de",)], "depot_added")
        self.assertEqual(states[("pl-pl",)], "depot_removed")

    def test_not_archived_game_plans_whole_build(self):
        self.w.add_game("100", "alpha")
        p = app.plan_update("100")["plan"]
        self.assertEqual(p["state"], "not_archived")
        self.assertEqual(p["counts"]["changed"] + p["counts"]["removed"], 0)
        self.assertGreater(p["counts"]["added"], 0)
        self.assertGreater(p["download_bytes"], 0)
        self.assertEqual(self.fetched, [])

    def test_no_change_plan_has_no_unchanged_list(self):
        self._archived()
        self._new_build()
        self.w.manifests = {k: v for k, v in self.w.manifests.items()}
        b1 = {d["manifest"]: d for d in self.w.metas["100"]["depots"]}
        # B2 with exactly B1's file contents: point B2's manifests at B1's
        for d in self.w.metas["100"]["depots"]:
            self.w.manifests[d["manifest"]] = self.w.manifests[d["manifest"].replace("B2", "B1")]
        p = app.plan_update("100")["plan"]
        self.assertEqual(p["state"], "up_to_date")
        self.assertTrue(all("unchanged" not in g for g in self._plan_file()["groups"]))
        self.assertTrue(b1)

    def test_plan_matches_the_real_update(self):
        """The plan predicts exactly the chunks the real 'Update all' then downloads."""
        self._archived()
        self._new_build()
        cdn, mans, meta = self.w.cdn, self.w.manifests, self.w.metas["100"]
        neutral = next(d["manifest"] for d in meta["depots"] if d["languages"] == ["*"])
        both = b"NEW-SHARED-BYTES" * 4                       # one chunk shared by two new files
        mans[neutral]["depot"]["items"] += [_file("data\\new1.dat", both, cdn),
                                            _file("data\\new2.dat", both, cdn)]
        shared_md5 = hashlib.md5(zlib.compress(both)).hexdigest()
        lost_md5 = hashlib.md5(zlib.compress(b"en-100")).hexdigest()    # lang\en.txt: same in B1 and B2
        arc = self.arc()
        arc.chunk_path(lost_md5).unlink()                    # lost from the archive

        seen = {}
        orig_diff = DA.diff_manifests

        def spy(*a, **kw):
            r = orig_diff(*a, **kw)
            seen.update(r["download_set"])
            return r
        DA.diff_manifests = spy
        try:
            plan = app.plan_update("100")["plan"]
        finally:
            DA.diff_manifests = orig_diff
        self.assertEqual(self.fetched, [])

        self.assertTrue(app._archive_all_worker())
        got = set(self.fetched)
        self.assertEqual(set(seen), got)                                       # same chunk set
        self.assertEqual(plan["download_bytes"], sum(len(cdn[m]) for m in got))  # same bytes
        self.assertEqual(plan["download_chunks"], len(got))
        self.assertEqual(self.fetched.count(shared_md5), 1)                    # shared: fetched once
        self.assertIn(lost_md5, got)                                           # lost: fetched…
        detail = self._plan_file()
        en = [e for g in detail["groups"] for e in g.get("unchanged") or [] if e["path"] == "lang\\en.txt"]
        self.assertEqual(en[0]["missing_chunks"], 1)                           # …reported as repair,
        self.assertNotIn("lang\\en.txt", [e["path"] for g in detail["groups"] for e in g["changed"]])
        self.assertIn("chunk_missing_in_archive", [i["issue"] for i in detail["issues"]])
        self.assertEqual(sorted(e["path"] for g in detail["groups"] for e in g["added"]),
                         ["data\\new1.dat", "data\\new2.dat"])

    def test_concurrent_status_writes_keep_every_game(self):
        import threading
        errs = []

        def one(i):
            try:
                app._write_update_plan(str(i), {"product_id": str(i), "state": "up_to_date"}, {"groups": []})
            except Exception as exc:                                         # pragma: no cover
                errs.append(exc)
        ts = [threading.Thread(target=one, args=(i,)) for i in range(25)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(errs, [])
        self.assertEqual(sorted(self._status()["update_plans"], key=int), [str(i) for i in range(25)])
        self.assertEqual(len(list((app.BASE / "_depots" / "exchange" / "plans").glob("*.json"))), 25)
        self.assertFalse(list((app.BASE / "_depots" / "exchange").rglob("*.tmp*")))
