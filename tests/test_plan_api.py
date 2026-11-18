"""Update plan endpoints (plan_update, plan_update_all, get_update_plan, get_update_plans) and the UI wiring
in assets/index.html. Synthetic GOG from test_archive — no network, no real archive."""
import hashlib, json, os, re, sys, threading, time, unittest, zlib
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app
import depot_archive as DA
from test_archive import ArchiveTestBase, _file

ROOT = Path(__file__).resolve().parent.parent


class PlanApiBase(ArchiveTestBase):
    def setUp(self):
        super().setUp()
        self._saved = {k: getattr(app, k) for k in ("_plan_update", "_fetch_build_and_meta")}
        self.addCleanup(lambda: [setattr(app, k, v) for k, v in self._saved.items()])
        self.addCleanup(lambda: (app._PLAN_ALL["cancel"].set(), self._join()))
        app._PLAN_EPOCH.clear()

    def _join(self):
        t = app._PLAN_ALL["thread"]
        if t is not None:
            t.join(10)

    def ex(self):
        return app.BASE / "_depots" / "exchange"

    def status(self):
        return json.loads((self.ex() / "status.json").read_text(encoding="utf-8"))

    def archived(self, pid="100", slug="alpha", **kw):
        self.w.add_game(pid, slug, **kw)
        self.assertTrue(app._archive_all_worker(only_ids={pid}))
        self.fetched.clear()

    def new_build(self, pid="100", slug="alpha", **kw):
        keep = [g for g in self.w.games if g["id"] != pid]
        self.w.add_game(pid, slug, build_id="B2", installers=False, **kw)
        self.w.games = keep + [self.w.games[-1]]

    def listed(self, pid, slug):
        """A game GOG has an installer for on this OS (a plan-all target even when not archived)."""
        self.w.add_game(pid, slug)
        self.w.games[-1]["product"]["downloads"] = {"installers": [{"os": app._MY_OS}]}

    def neutral(self, pid="100"):
        return next(d["manifest"] for d in self.w.metas[pid]["depots"]
                    if d["languages"] == ["*"] and d["productId"] == pid)


class Endpoints(PlanApiBase):
    def test_plan_update_returns_plan_without_downloading_chunks(self):
        self.archived()
        self.new_build()
        r = app.plan_update("100")
        self.assertTrue(r["ok"], r)
        p = r["plan"]
        self.assertEqual(p["ui_state"], "plan_ready")
        self.assertEqual(p["counts"]["changed"], 1)
        for k in ("repair_bytes", "repair_unique_bytes", "ambiguous_files", "ambiguous_groups", "depot_groups"):
            self.assertIn(k, p)
        self.assertEqual(self.fetched, [])
        self.assertIsNone(self.arc().read_record("100", "B2"))

    def test_status_holds_summaries_and_plans_file_holds_lists(self):
        self.archived()
        self.new_build()
        app.plan_update("100")
        s = self.status()["update_plans"]["100"]
        for k in ("changed", "added", "removed", "unchanged", "items"):
            self.assertNotIn(k, s)
        self.assertTrue(all(isinstance(v, int) for v in s["counts"].values()))
        detail = json.loads((self.ex() / "plans" / "100.json").read_text(encoding="utf-8"))
        self.assertEqual([e["path"] for g in detail["groups"] for e in g["changed"]], ["bin\\game.exe"])

    def test_get_update_plans_reads_no_plan_file_and_get_update_plan_reads_one(self):
        self.archived()
        self.w.add_game("200", "beta")
        self.new_build()
        app.plan_update("100")
        app.plan_update("200")
        reads = []
        orig = DA._read_json
        DA._read_json = lambda p: reads.append(Path(p)) or orig(p)
        try:
            r = app.get_update_plans()
            self.assertEqual(sorted(x["product_id"] for x in r["plans"]), ["100", "200"])
            self.assertFalse([p for p in reads if "plans" in p.parts])
            reads.clear()
            d = app.get_update_plan("100", "changed")
            self.assertEqual([p.name for p in reads if "plans" in p.parts], ["100.json"])
        finally:
            DA._read_json = orig
        self.assertEqual([e["path"] for e in d["items"]], ["bin\\game.exe"])

    def test_list_is_paged_by_500_and_filtered_by_path(self):
        self.w.add_game("100", "alpha")
        cdn = self.w.cdn
        items = self.w.manifests[self.neutral()]["depot"]["items"]
        items += [_file(f"maps\\m{i:04d}.dat", f"MAP{i}".encode(), cdn) for i in range(1200)]
        app.plan_update("100")
        d = app.get_update_plan("100", "added")
        self.assertEqual(len(d["items"]), 500)
        self.assertGreater(d["remaining"], 700)
        self.assertEqual(d["total"], d["remaining"] + 500)
        d = app.get_update_plan("100", "added", query="M01")
        self.assertEqual(d["total"], 100)                      # m0100…m0199, case-insensitive
        d = app.get_update_plan("100", "added", offset=1100)
        self.assertEqual(d["offset"], 1100)
        self.assertEqual(d["remaining"], 0)
        self.assertFalse(app.get_update_plan("100", "everything")["ok"])

    def test_first_archive_state(self):
        self.w.add_game("100", "alpha")
        p = app.plan_update("100")["plan"]
        self.assertEqual((p["state"], p["ui_state"]), ("not_archived", "first_archive"))
        self.assertEqual(self.fetched, [])

    def test_v1_unavailable_is_visible_and_not_an_error(self):
        self.archived()
        app._fetch_build_and_meta = lambda pid: (
            {"build_id": "V1B", "generation": "1"},
            {"buildId": "V1B", "contentSystem": 1, "products": [{"productId": "100"}],
             "depots": [{"productId": "100", "languages": ["*"], "manifest": "f" * 32}]})
        r = app.plan_update("100")
        self.assertTrue(r["ok"])
        self.assertEqual(r["plan"]["ui_state"], "v1_unavailable")
        self.assertIn("cały depot", r["plan"]["reason"])

    def test_skipped_is_its_own_state(self):
        self.archived()
        app._fetch_build_and_meta = lambda pid: (_ for _ in ()).throw(RuntimeError("brak buildów"))
        p = app.plan_update("100")["plan"]
        self.assertEqual(p["ui_state"], "skipped")
        self.assertTrue(p["reason"])

    def test_ambiguous_path_is_visible_and_starts_nothing(self):
        self.archived()
        self.new_build()
        meta, cdn = self.w.metas["100"], self.w.cdn
        mid = "100n2B2"                                         # 2nd neutral depot: same key, same path
        self.w.manifests[mid] = {"depot": {"items": [_file("bin\\game.exe", b"OTHER-EXE", cdn)]}}
        meta["depots"].append({"productId": "100", "languages": ["*"], "manifest": mid})
        p = app.plan_update("100")["plan"]
        self.assertEqual(p["ui_state"], "ambiguous_path")
        self.assertEqual((p["ambiguous_files"], p["ambiguous_groups"]), (1, 1))
        d = app.get_update_plan("100", "changed")
        self.assertEqual([i["path"] for i in d["ambiguous"]], ["bin\\game.exe"])
        self.assertEqual(self.fetched, [])
        self.assertIsNone(self.arc().read_record("100", "B2"))   # no update ran
        self.assertFalse(app._is_running)
        self.assertEqual(list(app._task_queue), [])

    def test_repair_unique_bytes_counts_a_shared_lost_chunk_once(self):
        twin = b"TWIN-BYTES" * 7

        def twins():
            items = self.w.manifests[self.neutral()]["depot"]["items"]
            items += [_file("data\\t1.dat", twin, self.w.cdn), _file("data\\t2.dat", twin, self.w.cdn)]
        self.w.add_game("100", "alpha")
        twins()
        self.assertTrue(app._archive_all_worker())
        self.new_build()
        twins()
        md5 = hashlib.md5(zlib.compress(twin)).hexdigest()
        self.arc().chunk_path(md5).unlink()
        p = app.plan_update("100")["plan"]
        size = len(self.w.cdn[md5])
        self.assertEqual(p["repair_bytes"], 2 * size)          # per file
        self.assertEqual(p["repair_unique_bytes"], size)       # unique
        d = app.get_update_plan("100", "repair")
        self.assertEqual(sorted(e["path"] for e in d["items"]), ["data\\t1.dat", "data\\t2.dat"])
        self.assertNotIn("data\\t1.dat", [e["path"] for e in app.get_update_plan("100", "changed")["items"]])


class PlanAll(PlanApiBase):
    def test_games_run_one_after_another(self):
        for pid, slug in (("100", "alpha"), ("200", "beta"), ("300", "gamma")):
            self.listed(pid, slug)
        active, peak, order = [0], [0], []
        lock = threading.Lock()

        def fake(g):
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            order.append(g["id"])
            time.sleep(0.05)
            with lock:
                active[0] -= 1
            return ({"product_id": g["id"], "title": g["title"], "state": "up_to_date"}, None)
        app._plan_update = fake
        self.assertTrue(app.plan_update_all()["ok"])
        self.assertFalse(app.plan_update_all()["ok"])           # never two runs at once
        self._join()
        self.assertEqual(peak[0], 1)
        self.assertEqual(order, ["100", "200", "300"])
        run = self.status()["plan_run"]
        self.assertEqual((run["done"], run["total"], run["errors"]), (3, 3, 0))
        self.assertTrue(run["finished"])
        done = [m for m in self.sent if m.get("type") == "plan_all_done"]
        self.assertEqual(len(done), 1)
        self.assertFalse(app._is_running)                       # no auto-update afterwards
        self.assertEqual(self.fetched, [])

    def test_does_not_block_the_download_queue(self):
        self.listed("100", "alpha")
        gate, inside = threading.Event(), threading.Event()

        def slow(g):
            inside.set()
            gate.wait(5)
            return ({"product_id": g["id"], "title": g["title"], "state": "up_to_date"}, None)
        app._plan_update = slow
        app.plan_update_all()
        self.assertTrue(inside.wait(5))
        ran = threading.Event()
        r = app._submit_task(lambda: ran.set() or True, "DOWNLOAD", queueable=True)
        self.assertTrue(r.get("started"), r)                    # started at once, not queued behind the plan
        self.assertTrue(ran.wait(5))
        self.assertTrue(app._plan_all_running())
        gate.set()
        self._join()
        for _ in range(50):
            if not app._is_running:
                break
            time.sleep(0.05)

    def test_update_started_during_planning_marks_that_plan_stale_only(self):
        self.listed("100", "alpha")
        self.listed("200", "beta")
        gate = threading.Event()

        def fake(g):
            if g["id"] == "100":
                gate.wait(5)
            return ({"product_id": g["id"], "title": g["title"], "state": "up_to_date"}, None)
        app._plan_update = fake
        app.plan_update_all()
        time.sleep(0.1)
        app._mark_plans_stale(["100"])                          # what update_game("100") does first
        gate.set()
        self._join()
        plans = self.status()["update_plans"]
        self.assertTrue(plans["100"].get("stale"))
        self.assertFalse(plans["200"].get("stale"))

    def test_update_game_marks_saved_plan_stale(self):
        self.archived()
        app.plan_update("100")
        self.assertFalse(self.status()["update_plans"]["100"].get("stale"))
        app._mark_plans_stale(["100"])
        self.assertTrue(self.status()["update_plans"]["100"]["stale"])

    def test_interrupted_run_leaves_valid_status(self):
        self.listed("100", "alpha")
        self.listed("200", "beta")
        calls = []

        def crash(g):
            calls.append(g["id"])
            if len(calls) == 2:
                raise SystemExit("process killed")             # passes through `except Exception`
            return ({"product_id": g["id"], "title": g["title"], "state": "up_to_date"}, None)
        app._plan_update = crash
        app._PLAN_ALL["cancel"].clear()                         # plan_update_all does this before a run
        with self.assertRaises(SystemExit):
            app._plan_all_worker(app._plan_all_targets())
        st = self.status()                                      # parses: never half-written
        self.assertIsNone(st["plan_run"]["finished"])
        self.assertTrue(app.get_update_plans()["run"]["interrupted"])
        self.assertIn("100", st["update_plans"])

    def test_failed_status_write_keeps_previous_file(self):
        self.archived()
        app.plan_update("100")
        before = (self.ex() / "status.json").read_bytes()
        orig = os.replace

        def boom(src, dst):
            if str(dst).endswith("status.json"):
                raise OSError("disk gone")
            return orig(src, dst)
        os.replace = boom
        try:
            self.assertFalse(app.plan_update("100")["ok"])
        finally:
            os.replace = orig
        self.assertEqual((self.ex() / "status.json").read_bytes(), before)
        json.loads(before)

    def test_targets_include_v1_and_unarchived_games(self):
        self.archived()
        self.w.add_game("200", "beta")
        self.w.games[-1]["product"]["downloads"] = {"installers": [{"os": app._MY_OS}]}
        self.w.add_game("300", "gamma")                         # nothing for this OS, not archived
        self.assertEqual([g["id"] for g in app._plan_all_targets()], ["100", "200"])


class StatCount:
    """Counts DepotArchive.has_chunk calls (the plan's per-chunk lookups) while active."""

    def __init__(self, slow=None):
        self.calls, self.slow = [], slow or {}

    def __enter__(self):
        self.orig = DA.DepotArchive.has_chunk
        me = self

        def counted(arc, md5, compressed_size=None):
            me.calls.append(md5)
            if md5 in me.slow:
                time.sleep(me.slow[md5])
            return me.orig(arc, md5, compressed_size)
        DA.DepotArchive.has_chunk = counted
        return self

    def __exit__(self, *a):
        DA.DepotArchive.has_chunk = self.orig


def _md5(data: bytes) -> str:
    return hashlib.md5(zlib.compress(data)).hexdigest()


REDIST = _md5(b"REDIST-DirectX")
SHARED_MD5 = _md5(b"SHARED-RUNTIME-BYTES" * 3)
SFC_MD5 = _md5(b"aaaabbbb")          # every synthetic game has the same small files container


class FirstArchiveDependenciesOnly(PlanApiBase):
    """plan_first_archive_mode = "dependencies_only": only shared redist chunks are looked up."""

    def setUp(self):
        super().setUp()
        self.settings["plan_first_archive_mode"] = "dependencies_only"

    def spy_plan(self, gid):
        """plan_update + the set of chunks the plan counted as missing (from diff_manifests' download_set)."""
        seen, orig = {}, DA.diff_manifests

        def spy(*a, **kw):
            r = orig(*a, **kw)
            seen.update(r["download_set"])
            return r
        DA.diff_manifests = spy
        try:
            return app.plan_update(gid)["plan"], seen
        finally:
            DA.diff_manifests = orig

    def drop_shared(self, pid):
        """Remove what every synthetic game shares (data\\shared.dat, the small files container) from this game."""
        m = self.w.manifests[self.neutral(pid)]["depot"]
        m["items"] = [i for i in m["items"] if i.get("path") != "data\\shared.dat" and not i.get("sfcRef")]
        m.pop("smallFilesContainer", None)

    def test_looks_up_only_dependency_chunks(self):
        self.listed("200", "beta")
        self.w.add_game("200", "beta", deps=("DirectX",))
        self.w.games = [g for g in self.w.games if g["id"] != "200"][:0] + [self.w.games[-1]]
        with StatCount() as sc:
            p = app.plan_update("200")["plan"]
        self.assertEqual(p["ui_state"], "first_archive")
        self.assertEqual(sorted(set(sc.calls)), [REDIST])          # never a chunk of the game itself
        self.assertEqual(p["checked_chunks"], 1)
        self.assertTrue(p["shared_dependency_check"])
        self.assertEqual(p["first_archive_check"], "dependencies_only")
        self.assertNotIn("estimate", p)
        self.assertNotIn("estimate_kind", p)
        self.assertEqual((p["counts"]["changed"], p["counts"]["removed"], p["counts"]["unchanged"]), (0, 0, 0))
        self.assertGreater(p["counts"]["added"], 0)
        self.assertEqual((p["repair_bytes"], p["repair_unique_bytes"]), (0, 0))
        self.assertIn("nie ma pobranych danych depotu", p["reason"])
        self.assertEqual(self.fetched, [])

    def test_redist_present_from_another_game_is_reused_not_downloaded(self):
        self.archived("100", "alpha", deps=("DirectX",))
        self.w.add_game("200", "beta", deps=("DirectX",))
        p, missing = self.spy_plan("200")
        self.assertNotIn(REDIST, missing)
        self.assertEqual(p["reused_bytes"], len(self.w.cdn[REDIST]))
        self.assertEqual(p["download_bytes"], sum(missing.values()))

    def test_redist_also_in_a_game_depot_counts_once(self):
        self.w.add_game("200", "beta", deps=("DirectX",))
        self.w.manifests[self.neutral("200")]["depot"]["items"].append(
            _file("bin\\DirectX_copy.exe", b"REDIST-DirectX", self.w.cdn))       # same bytes = same chunk
        p, missing = self.spy_plan("200")
        self.assertIn(REDIST, missing)
        self.assertEqual(p["download_bytes"], sum(missing.values()))
        self.assertEqual(p["download_chunks"], len(missing))

    def test_matches_the_real_archiving_when_nothing_of_the_game_is_shared(self):
        self.archived("100", "alpha", deps=("DirectX",))
        self.w.add_game("200", "beta", deps=("DirectX",))
        self.drop_shared("200")
        p, missing = self.spy_plan("200")
        self.assertTrue(app._archive_all_worker(only_ids={"200"}))
        got = set(self.fetched)
        self.assertEqual(got, set(missing))
        self.assertEqual(p["download_bytes"], sum(len(self.w.cdn[m]) for m in got))

    def test_game_chunk_shared_with_another_game_plan_is_an_upper_bound(self):
        self.archived("100", "alpha")                           # alpha holds data\\shared.dat
        self.w.add_game("200", "beta")                          # beta ships the same file
        p, missing = self.spy_plan("200")
        self.assertTrue(app._archive_all_worker(only_ids={"200"}))
        got = set(self.fetched)
        self.assertTrue(got <= set(missing))
        self.assertGreaterEqual(p["download_bytes"], sum(len(self.w.cdn[m]) for m in got))
        self.assertEqual(set(missing) - got, {SHARED_MD5, SFC_MD5})   # the difference: exactly the shared chunks

    def test_meta_or_manifest_only_counts_as_first_archive(self):
        self.w.add_game("200", "beta")
        arc = self.arc()
        arc.ensure()
        arc.put_meta("200", "B1", self.w.metas["200"])
        mid = self.neutral("200")
        arc.put_manifest("depot", mid, self.w.manifests[mid])
        p = app.plan_update("200")["plan"]
        self.assertEqual((p["state"], p["ui_state"]), ("not_archived", "first_archive"))


class FirstArchiveFull(FirstArchiveDependenciesOnly):
    """Default plan_first_archive_mode = "full": every chunk looked up — exact even when another game or edition
    already holds part of the data."""

    def setUp(self):
        PlanApiBase.setUp(self)                                  # the default mode, no setting

    def build_chunks(self, pid):
        mans = [self.w.manifests[d["manifest"]] for d in self.w.metas[pid]["depots"]]
        return {(c.get("compressedMd5") or "").lower() for m in mans for c in DA.manifest_chunks(m)}

    def test_default_is_full_and_looks_up_every_chunk(self):
        self.assertEqual(app.DEFAULT_SETTINGS["plan_first_archive_mode"], "full")
        self.w.add_game("200", "beta", deps=("DirectX",))
        with StatCount() as sc:
            p = app.plan_update("200")["plan"]
        self.assertEqual(p["ui_state"], "first_archive")
        self.assertEqual(p["first_archive_check"], "full")
        self.assertNotIn("shared_dependency_check", p)
        self.assertEqual(set(sc.calls), self.build_chunks("200") | {REDIST})
        self.assertEqual(self.fetched, [])

    def test_unknown_mode_value_means_full(self):
        for v in ("", "deps", None, 1):
            self.settings["plan_first_archive_mode"] = v
            self.assertEqual(app._first_archive_mode(), "full", v)

    def test_shared_game_chunk_plan_equals_real_archiving(self):
        self.archived("100", "alpha")                            # alpha holds data\shared.dat + the SFC
        self.w.add_game("200", "beta")
        p, missing = self.spy_plan("200")
        self.assertNotIn(SHARED_MD5, missing)
        self.assertTrue(app._archive_all_worker(only_ids={"200"}))
        got = set(self.fetched)
        self.assertEqual(got, set(missing))                       # chunk for chunk
        self.assertEqual(p["download_bytes"], sum(len(self.w.cdn[m]) for m in got))   # byte for byte

    def test_another_edition_with_almost_all_data_shared(self):
        """Oblivion GOTY / GOTY Deluxe shape: the second edition ships the first one's files plus a little."""
        self.archived("100", "alpha")
        self.w.add_game("300", "alpha_deluxe", dlc_files=False, dlc_meta=False)
        cdn = self.w.cdn
        for d in self.w.metas["300"]["depots"]:                 # same file contents as alpha
            src = next(x for x in self.w.metas["100"]["depots"] if x["languages"] == d["languages"])
            self.w.manifests[d["manifest"]] = json.loads(json.dumps(self.w.manifests[src["manifest"]]))
        self.w.manifests[self.neutral("300")]["depot"]["items"].append(
            _file("deluxe\extra.pak", b"DELUXE-ONLY" * 9, cdn))
        p, missing = self.spy_plan("300")
        self.assertEqual(set(missing), {_md5(b"DELUXE-ONLY" * 9)})   # only what alpha does not have
        self.assertGreater(p["reused_bytes"], p["download_bytes"])
        self.assertTrue(app._archive_all_worker(only_ids={"300"}))
        self.assertEqual(set(self.fetched), set(missing))
        self.assertEqual(p["download_bytes"], sum(len(self.w.cdn[m]) for m in self.fetched))

    # the dependencies_only expectations that do not hold in full mode
    test_looks_up_only_dependency_chunks = None
    test_game_chunk_shared_with_another_game_plan_is_an_upper_bound = None
    test_redist_present_from_another_game_is_reused_not_downloaded = None   # full: shared game data is reused too


class UniquePaths(PlanApiBase):
    def test_same_path_in_several_language_depots_counts_once(self):
        self.w.add_game("200", "beta", langs=("en", "pl", "de"))    # goggame-200.info in each language depot
        p = app.plan_update("200")["plan"]
        self.assertEqual(p["counts"]["added"] - p["counts_unique"]["added"], 2)
        uq = app.get_update_plan("200", "added")
        al = app.get_update_plan("200", "added", unique=False)
        self.assertTrue(uq["unique"])
        self.assertEqual(al["total"] - uq["total"], 2)
        self.assertEqual(uq["list_sizes_unique"]["added"], p["counts_unique"]["added"])
        self.assertEqual(uq["list_sizes_entries"]["added"], p["counts"]["added"])
        info = next(e for e in uq["items"] if e["path"] == "goggame-200.info")
        self.assertEqual(info["entries"], 3)
        self.assertEqual(len(info["groups"]), 3)
        self.assertEqual(sum(1 for e in al["items"] if e["path"] == "goggame-200.info"), 3)

    def test_no_unchanged_list_means_unknown_unique_unchanged(self):
        self.archived()
        self.new_build()
        p = app.plan_update("100")["plan"]
        self.assertIsInstance(p["counts_unique"]["unchanged"], int)   # a change: the unchanged list is kept
        self.assertEqual(app._unique_path_counts([{"added": [], "changed": []}])["unchanged"], None)


class IncompleteArchive(PlanApiBase):
    def interrupted(self):
        """beta's archiving fails half way: an incomplete record and part of its chunks stay."""
        self.listed("200", "beta")
        n = [0]

        def fail(md5):
            n[0] += 1
            if n[0] > 3:
                raise RuntimeError("sieć zerwana")
        self.fail_fetch = fail
        app._archive_all_worker(only_ids={"200"})
        self.fail_fetch = None
        recs = self.arc().list_records("200")
        self.assertEqual([r["state"] for r in recs], [DA.STATE_INCOMPLETE])
        self.fetched.clear()

    def test_separate_state_every_chunk_looked_up_and_exact(self):
        self.interrupted()
        arc_files = lambda: sorted((p.as_posix(), p.stat().st_size) for p in (app.BASE / "_depots").rglob("*")
                                   if p.is_file() and "exchange" not in p.parts)
        before = arc_files()
        seen, orig = {}, DA.diff_manifests

        def spy(*a, **kw):
            r = orig(*a, **kw)
            seen.update(r["download_set"])
            return r
        DA.diff_manifests = spy
        try:
            with StatCount() as sc:
                p = app.plan_update("200")["plan"]
        finally:
            DA.diff_manifests = orig
        self.assertEqual((p["state"], p["ui_state"]), ("incomplete_archive", "incomplete_archive"))
        self.assertNotIn(p["ui_state"], ("up_to_date", "first_archive"))
        build_chunks = {(c.get("compressedMd5") or "").lower() for d in self.w.metas["200"]["depots"]
                        for c in DA.manifest_chunks(self.w.manifests[d["manifest"]])}
        self.assertEqual(set(sc.calls), build_chunks)                      # every chunk of the build
        self.assertEqual(p["checked_chunks"], len(build_chunks))
        self.assertGreater(p["reused_bytes"], 0)                           # part of it is there already
        self.assertIn("nic nie zostanie usunięte", p["reason"])
        self.assertEqual(arc_files(), before)                              # nothing touched by the plan
        self.assertTrue(app._archive_all_worker(only_ids={"200"}))         # finish the archiving
        got = set(self.fetched)
        self.assertEqual(got, set(seen))                                    # exactly what the plan said
        self.assertEqual(p["download_bytes"], sum(len(self.w.cdn[m]) for m in got))


class Timeouts(PlanApiBase):
    def setUp(self):
        super().setUp()
        self._consts = {k: getattr(app, k) for k in ("_PLAN_HTTP_TIMEOUT", "_PLAN_BATCH")}
        self.addCleanup(lambda: [setattr(app, k, v) for k, v in self._consts.items()])

    def run_all(self):
        app._PLAN_ALL["cancel"].clear()
        t0 = time.monotonic()
        run = app._plan_all_worker(app._plan_all_targets())
        return run, time.monotonic() - t0

    def test_setting_values(self):
        for v, want in ((None, 300), (0, 300), (-5, 300), ("abc", 300), (12, 12), ("7.5", 7.5)):
            self.settings["plan_timeout_seconds"] = v
            self.assertEqual(app._plan_timeout_seconds(), want, v)

    def test_manifest_deadline_stops_that_game_only(self):
        self.listed("100", "alpha")
        self.listed("200", "beta")
        app._PLAN_HTTP_TIMEOUT = 0.15
        slow_game = {d["manifest"] for d in self.w.metas["100"]["depots"]}
        inner = app._cdn_depot_manifest

        def manifest(d):
            if d["manifest"] in slow_game:
                time.sleep(0.1)
            return inner(d)
        app._cdn_depot_manifest = manifest
        run, _ = self.run_all()
        st = self.status()                                              # valid JSON after the timeout
        a, b = st["update_plans"]["100"], st["update_plans"]["200"]
        self.assertEqual((a["state"], a.get("error_kind")), ("error", "plan_timeout"))
        self.assertIn("manifesty", a["reason"])
        self.assertEqual(b["ui_state"], "first_archive")
        self.assertEqual((run["done"], run["errors"]), (2, 1))

    def test_deadline_in_the_middle_of_chunk_batches_next_game_does_not_wait(self):
        self.archived("100", "alpha")
        self.new_build("100", "alpha")                                   # full comparison: every chunk
        self.listed("200", "beta")                                       # first_archive, no deps: no stat
        self.settings["plan_timeout_seconds"] = 0.4
        app._PLAN_BATCH = 2
        a_chunks = {(c.get("compressedMd5") or "").lower() for d in self.w.metas["100"]["depots"]
                    for c in DA.manifest_chunks(self.w.manifests[d["manifest"]])}
        with StatCount(slow={m: 0.15 for m in a_chunks}) as sc:
            run, took = self.run_all()
            calls_at_end = len(sc.calls)
            time.sleep(0.5)                                              # started lookups may finish
            self.assertLessEqual(len(sc.calls) - calls_at_end, 4)       # cancelled ones never ran
        a = self.status()["update_plans"]["100"]
        self.assertEqual(a.get("error_kind"), "plan_timeout")
        self.assertIn("chunki", a["reason"])
        self.assertLess(len(set(sc.calls) & a_chunks), len(a_chunks))  # stopped part way
        b = self.status()["update_plans"]["200"]
        self.assertEqual(b["ui_state"], "first_archive")
        self.assertLess(b["plan_seconds"], 0.3)                          # did not wait for alpha's batch
        self.assertLess(took, 2.0)

    def test_hung_plan_is_left_behind_and_its_late_result_is_dropped(self):
        self.listed("100", "alpha")
        self.listed("200", "beta")
        self.settings["plan_timeout_seconds"] = 0.3
        gate, finished = threading.Event(), threading.Event()
        real = app._plan_update

        def hung(g):
            if g["id"] == "100":
                gate.wait(5)                                             # ignores the deadline
                finished.set()
                return ({"product_id": "100", "title": "alpha", "state": "up_to_date"}, None)
            return real(g)
        app._plan_update = hung
        run, took = self.run_all()
        self.assertLess(took, 2.0)                                      # did not wait for the hung thread
        self.assertEqual(self.status()["update_plans"]["100"].get("error_kind"), "plan_timeout")
        self.assertEqual(self.status()["update_plans"]["200"]["ui_state"], "first_archive")
        gate.set()
        self.assertTrue(finished.wait(5))
        time.sleep(0.1)
        st = self.status()                                              # still valid JSON
        self.assertEqual(st["update_plans"]["100"].get("error_kind"), "plan_timeout")   # late result dropped
        self.assertEqual(st["plan_run"]["done"], 2)


class Workers(PlanApiBase):
    def setUp(self):
        super().setUp()
        self._net = app._is_network_path
        self.addCleanup(lambda: setattr(app, "_is_network_path", self._net))

    def test_defaults_setting_and_network_path(self):
        app._is_network_path = lambda p: False
        self.assertEqual(app._plan_workers(), 4)
        app._is_network_path = lambda p: True
        self.assertEqual(app._plan_workers(), 2)
        self.settings["plan_verify_workers"] = 3
        self.assertEqual(app._plan_workers(), 3)
        self.settings["plan_verify_workers"] = 99
        self.assertEqual(app._plan_workers(), 16)

    def test_one_executor_for_a_whole_plan_all_run(self):
        for i in range(5):
            self.listed(str(100 + i), f"g{i}")
        app._PLAN_POOL["ex"], app._PLAN_POOL["n"] = None, 0
        made = []
        real = app.ThreadPoolExecutor

        class Counting(real):
            def __init__(self, *a, **kw):
                made.append(kw.get("max_workers") or (a[0] if a else None))
                super().__init__(*a, **kw)
        app.ThreadPoolExecutor = Counting
        try:
            app._PLAN_ALL["cancel"].clear()
            run = app._plan_all_worker(app._plan_all_targets())
        finally:
            app.ThreadPoolExecutor = real
        self.assertEqual(run["done"], 5)
        self.assertEqual(made, [4])                            # one pool, default size, reused by every game

    def test_every_lost_chunk_is_found_with_few_workers(self):
        for n in (1, 2):
            with self.subTest(workers=n):
                self.settings["plan_verify_workers"] = n
                pid = str(500 + n)
                self.w.add_game(pid, f"lost{n}")
                self.assertTrue(app._archive_all_worker(only_ids={pid}))
                self.new_build(pid, f"lost{n}")
                lost = [hashlib.md5(zlib.compress(f"{l}-{pid}".encode())).hexdigest() for l in ("en", "pl")]
                for m in lost:
                    self.arc().chunk_path(m).unlink()
                p = app.plan_update(pid)["plan"]
                self.assertEqual(p["repair_unique_bytes"], sum(len(self.w.cdn[m]) for m in lost))
                self.assertGreater(p["checked_chunks"], 0)


class IsolatedExchange(PlanApiBase):
    def test_plans_go_only_to_the_given_exchange_dir(self):
        self.archived()
        self.listed("200", "beta")                              # not archived: first_archive
        self.new_build()
        root = Path(self._tmp.name)
        ex_dir = root.parent / (root.name + "-exchange")
        self.addCleanup(lambda: __import__("shutil").rmtree(ex_dir, ignore_errors=True))
        os.environ["GOGGUI_EXCHANGE_DIR"] = str(ex_dir)
        self.addCleanup(lambda: os.environ.pop("GOGGUI_EXCHANGE_DIR", None))

        def snap():
            return {str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
                    for p in root.rglob("*")} | {"<dirs>": tuple(sorted(str(d) for d in root.rglob("*") if d.is_dir()))}
        before = snap()
        self.assertTrue(app.plan_update("100")["ok"])
        app._PLAN_ALL["cancel"].clear()
        app._plan_all_worker(app._plan_all_targets())
        app.get_update_plan("100", "changed")
        app.get_update_plans()
        self.assertEqual(snap(), before)                        # nothing under BASE / archive / games changed
        self.assertFalse((app.BASE / "_depots" / "exchange").exists())
        files = sorted(p.relative_to(ex_dir).as_posix() for p in ex_dir.rglob("*") if p.is_file())
        self.assertEqual([f for f in files if not f.startswith("manifests/")],
                         ["plans/100.json", "plans/200.json", "status.json"])
        self.assertTrue(all(re.fullmatch(r"manifests/(depot|dep)-[^/]+\.json", f)
                            for f in files if f.startswith("manifests/")))   # saved for "Wykonaj plan"
        self.assertEqual(self.fetched, [])

    def test_setting_exchange_dir_when_no_env(self):
        os.environ.pop("GOGGUI_EXCHANGE_DIR", None)
        self.settings["exchange_dir"] = str(Path(self._tmp.name) / "ex2")
        self.assertEqual(app._exchange_dir(), Path(self._tmp.name) / "ex2")
        self.settings["exchange_dir"] = ""
        self.assertEqual(app._exchange_dir(), app._archive_root() / "exchange")


class Performance(PlanApiBase):
    """Timing of 'Check plan' over 30 synthetic games: per game and total, chunks looked up — in the log."""
    N = 30

    def test_plan_all_timing_is_logged(self):
        for i in range(self.N):
            self.listed(str(1000 + i), f"perf{i}")
        self.assertTrue(app._archive_all_worker())
        self.fetched.clear()
        for i in range(0, self.N, 2):                           # every other game: a new build
            self.new_build(str(1000 + i), f"perf{i}")
            self.w.games[-1]["product"]["downloads"] = {"installers": [{"os": app._MY_OS}]}
        self.w.games.sort(key=lambda g: g["id"])
        lines = []
        app.log = lambda m: lines.append(m)
        app._PLAN_ALL["cancel"].clear()
        t0 = time.monotonic()
        run = app._plan_all_worker(app._plan_all_targets())
        took = time.monotonic() - t0
        per_game = [l for l in lines if re.match(r"plan: .+ \[\d+\] \w+ \d+\.\d\ds, \d+ chunków sprawdzonych$", l)]
        total = [l for l in lines if l.startswith(f"plan wszystkich: {self.N}/{self.N} gier w ")]
        self.assertEqual(len(per_game), self.N)
        self.assertEqual(len(total), 1, lines[-3:])
        self.assertIn("chunków sprawdzonych", total[0])
        self.assertEqual(run["done"], self.N)
        self.assertGreater(run["checked_chunks"], 0)
        self.assertEqual(sum(1 for l in per_game if " plan_ready " in l), self.N // 2)
        self.assertEqual(self.fetched, [])
        self.assertLess(took, 60)                               # generous: a hang, not a tuning target
        sys.stderr.write(f"\n[pomiar] {total[0]}\n")


class Counter:
    """Wraps app.<name> and counts calls while active."""

    def __init__(self, *names):
        self.names, self.n, self.orig = names, {k: 0 for k in names}, {}

    def __enter__(self):
        for k in self.names:
            self.orig[k] = getattr(app, k)
            setattr(app, k, self._wrap(k, self.orig[k]))
        return self

    def _wrap(self, k, f):
        def w(*a, **kw):
            self.n[k] += 1
            return f(*a, **kw)
        return w

    def __exit__(self, *a):
        for k, f in self.orig.items():
            setattr(app, k, f)


class PlanExecute(PlanApiBase):
    """'Wykonaj plan': saved plans through the archive engine — no library scan, no new plan, only missing data."""

    def setUp(self):
        super().setUp()
        self.addCleanup(lambda: (app._PLAN_EXEC.clear(), app._PLAN_EXEC_QUEUED.clear()))

    def world(self):
        self.archived("100", "alpha")                            # → plan_ready (new build)
        self.new_build("100", "alpha")
        self.w.games[-1]["product"]["downloads"] = {"installers": [{"os": app._MY_OS}]}
        self.archived("200", "beta")                             # → up_to_date
        self.w.games[-1]["product"]["downloads"] = {"installers": [{"os": app._MY_OS}]}
        self.listed("300", "gamma")                              # → first_archive
        self.w.games.sort(key=lambda g: g["id"])

    def plan_all(self):
        seen, orig = {}, DA.diff_manifests

        def spy(*a, **kw):
            r = orig(*a, **kw)
            seen.update(r["download_set"])
            return r
        DA.diff_manifests = spy
        try:
            app._PLAN_ALL["cancel"].clear()
            app._plan_all_worker(app._plan_all_targets())
        finally:
            DA.diff_manifests = orig
        self.fetched.clear()
        return set(seen)

    def wait_queue(self):
        for _ in range(400):
            if not app._is_running and not app._task_queue:
                return
            time.sleep(0.025)
        self.fail("queue did not finish")

    def states(self):
        return {k: v["ui_state"] for k, v in self.status()["update_plans"].items()}

    def test_runs_only_executable_plans_without_rescanning_or_replanning(self):
        self.world()
        planned = self.plan_all()
        self.assertEqual(self.states(), {"100": "plan_ready", "200": "up_to_date", "300": "first_archive"})
        beta_before = self.arc().read_record("200", "B1")
        with Counter("scan_downloaded_games", "_plan_update", "_plan_all_targets", "_pick_build",
                     "_fetch_build_and_meta", "_cdn_depot_manifest", "_dependency_manifests",
                     "_update_worker") as c:
            r = app.plan_execute()
            self.assertTrue(r["ok"], r)
            self.assertEqual(r["count"], 2)
            self.assertEqual({s["product_id"] for s in r["skipped"]}, {"200"})
            self.wait_queue()
        self.assertEqual(c.n, {k: 0 for k in c.n})               # no scan, no plan, no metadata, no extras
        self.assertEqual(set(self.fetched), planned)             # exactly the planned missing chunks
        self.assertEqual(len(self.fetched), len(set(self.fetched)))
        self.assertEqual(self.arc().read_record("100", "B2")["state"], DA.STATE_COMPLETE)
        self.assertEqual(self.arc().read_record("300", "B1")["state"], DA.STATE_COMPLETE)
        self.assertEqual(self.arc().read_record("200", "B1"), beta_before)   # up to date: untouched
        plans = self.status()["update_plans"]
        self.assertTrue(plans["100"]["stale"] and plans["300"]["stale"])   # executed: re-plan before again
        self.assertFalse(plans["200"].get("stale"))
        report = [m for m in self.sent if m.get("type") == "migration_report"][-1]["report"]
        self.assertEqual(report["total"], 2)

    def test_chunks_already_present_are_not_downloaded(self):
        self.world()
        planned = self.plan_all()
        arrived = sorted(planned)[0]                              # e.g. stored by another run meanwhile
        self.arc().put_chunk(arrived, self.w.cdn[arrived])
        app.plan_execute()
        self.wait_queue()
        self.assertNotIn(arrived, self.fetched)
        self.assertEqual(set(self.fetched), planned - {arrived})

    def test_same_plan_is_never_queued_twice(self):
        self.world()
        self.plan_all()
        gate, inside = threading.Event(), threading.Event()
        orig = app._archive_all_loop

        def held(*a, **kw):
            inside.set()
            gate.wait(5)
            return orig(*a, **kw)
        app._archive_all_loop = held
        try:
            first = app.plan_execute()
            self.assertTrue(inside.wait(5))
            second = app.plan_execute()
            self.assertFalse(second["ok"])
            self.assertEqual(sorted(second["already_queued"]), ["100", "300"])
            self.assertEqual(list(app._task_queue), [])
        finally:
            gate.set()
            app._archive_all_loop = orig
        self.wait_queue()
        self.assertTrue(first["ok"])
        self.assertEqual(len(self.fetched), len(set(self.fetched)))

    def test_stale_plan_needs_this_game_rechecked_others_run(self):
        self.world()
        self.plan_all()
        app._mark_plans_stale(["300"])
        r = app.plan_execute()
        self.assertEqual(r["count"], 1)
        self.assertIn("Sprawdź plan tej gry ponownie", next(s["reason"] for s in r["skipped"] if s["product_id"] == "300"))
        self.wait_queue()
        self.assertEqual(self.arc().list_records("300"), [])
        self.assertEqual(self.arc().read_record("100", "B2")["state"], DA.STATE_COMPLETE)

    def test_other_configuration_means_recheck_and_no_download(self):
        self.world()
        self.plan_all()
        self.settings["update_langs"] = ["en", "de"]
        app.plan_execute()
        self.wait_queue()
        self.assertEqual(self.fetched, [])
        report = [m for m in self.sent if m.get("type") == "migration_report"][-1]["report"]
        self.assertEqual(len(report["skipped"]), 2)
        self.assertTrue(all("innej konfiguracji" in s["reason"] and "ponownie" in s["reason"] for s in report["skipped"]))

    def test_scope_changed_since_planning_is_skipped_by_the_engine(self):
        self.world()
        self.owned = {"100", "1001", "1002", "200", "2001", "2002", "300"}   # gamma's DLC not owned when planned
        self.plan_all()
        app.plan_execute()                                        # …but its DLC installer is on disk: the engine
        self.wait_queue()                                         # would archive more than the plan describes
        report = [m for m in self.sent if m.get("type") == "migration_report"][-1]["report"]
        gamma = [s for s in report["skipped"] if s["title"] == "Gamma"]
        self.assertTrue(gamma and "innej konfiguracji" in gamma[0]["reason"] and "ponownie" in gamma[0]["reason"],
                        report["skipped"])
        self.assertEqual(self.arc().list_records("300"), [])
        self.assertEqual(self.arc().read_record("100", "B2")["state"], DA.STATE_COMPLETE)   # the others run


class ListStatus(PlanApiBase):
    """Regression: '9 Years of Shadows' — a complete depot archive, installers removed by the migration, only game
    metadata in its folder: the list said 'Nie pobrana' and the 'Pobrane' filter left it out."""

    def test_complete_archive_without_installer_is_listed_as_in_archive(self):
        self.w.add_game("2099051765", "9_years_of_shadows")
        self.w.games[-1]["title"] = "9 Years of Shadows"
        self.assertTrue(app._archive_all_worker())
        folder = app.BASE / "9_years_of_shadows"
        import shutil
        shutil.rmtree(folder / "extras")                         # as on disk: no extras either
        (folder / "setup_9_years_of_shadows_0.9_(1000).exe").unlink()   # nor the synthetic old installer
        left = sorted(p.name for p in folder.iterdir())
        self.assertTrue(left and all(self.META_FILE.match(n) for n in left), left)   # metadata only
        for x in self.w.games:                                   # fields get_games reads from scan_games
            for k, v in (("icon", None), ("logo", None), ("background", None), ("platforms", ["windows"]),
                         ("languages", []), ("installable", True), ("release_date", None), ("rating", None),
                         ("rating_count", None), ("details", {})):
                x.setdefault(k, v)
        g = next(x for x in app.get_games() if x["id"] == "2099051765")
        self.assertEqual(self.arc().read_record("2099051765", "B1")["state"], DA.STATE_COMPLETE)
        self.assertFalse(g["downloaded"])                          # metadata is still not a download
        self.assertTrue(g["archived"])
        self.assertEqual(g["list_status"], "archived")

    def test_list_status_order(self):
        done, part = {"state": DA.STATE_COMPLETE}, {"state": DA.STATE_INCOMPLETE}
        self.assertEqual(app._list_status(True, True, done), "installed")
        self.assertEqual(app._list_status(False, True, done), "downloaded")
        self.assertEqual(app._list_status(False, False, done), "archived")
        self.assertEqual(app._list_status(False, False, part), "none")      # incomplete archive: not downloaded
        self.assertEqual(app._list_status(False, False, None), "none")

    def test_list_and_downloaded_filter_use_it(self):
        html = (ROOT / "assets" / "index.html").read_text(encoding="utf-8")
        self.assertIn("if (filterMode === 'downloaded') arr = arr.filter(g => g.downloaded || g.list_status === 'archived');", html)
        self.assertIn(": g.list_status === 'archived' ? t('status.inArchive')", html)


class UiWiring(unittest.TestCase):
    """index.html only binds UI to the Api; plan_view.js renders and never calls the Api."""

    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "assets" / "index.html").read_text(encoding="utf-8")
        cls.js = (ROOT / "assets" / "plan_view.js").read_text(encoding="utf-8")

    def test_plan_view_never_calls_the_api(self):
        self.assertNotIn("pywebview", self.js)
        self.assertNotRegex(self.js, r"\bcall\(")

    def test_index_never_loads_every_plan_file(self):
        self.assertNotIn("plans/", self.html)
        self.assertNotRegex(self.html, r"call\('get_update_plan'[^)]*\)\s*\)?\s*\.then\([^)]*forEach")
        # details only from the plan window's loader, with one game id
        uses = re.findall(r"call\('get_update_plan',\s*([^,)]+)", self.html)
        self.assertTrue(uses)
        self.assertTrue(all(u.strip() == "_plan.gid" for u in uses), uses)
        self.assertIn("call('get_update_plans')", self.html)

    def test_plan_button_and_update_button_are_separate(self):
        self.assertIn('id="planBtn"', self.html)
        self.assertIn('id="updateBtn"', self.html)
        self.assertIn('id="tbPlanAll"', self.html)
        self.assertIn('<script src="plan_view.js"></script>', self.html)

    def test_details_window_sits_above_the_every_game_table(self):
        z = re.search(r"#planModal\s*\{\s*z-index:\s*(\d+)", self.html)
        base = re.search(r"\.settings-overlay\s*\{[^}]*z-index:\s*(\d+)", self.html)
        self.assertTrue(z and base)
        self.assertGreater(int(z.group(1)), int(base.group(1)))
        self.assertIn("PlanView.defaultKind(r.list_sizes)", self.html)

    def test_plan_view_is_bundled(self):
        spec = (ROOT / "GOGManager.spec").read_text(encoding="utf-8")
        self.assertIn("assets/plan_view.js", spec)


@unittest.skipUnless(__import__("shutil").which("node"), "Node.js not installed")
class PlanViewJs(unittest.TestCase):
    def test_inline_ui_script_parses(self):
        """The UI script lives inside index.html: a stray raw newline in a string breaks the whole page."""
        import subprocess, tempfile
        html = (ROOT / "assets" / "index.html").read_text(encoding="utf-8")
        code = chr(10).join(re.findall(r"<script>(.*?)</script>", html, re.S))
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "inline.js"
            f.write_text(code, encoding="utf-8")
            r = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])

    def test_node_suite(self):
        import subprocess
        r = subprocess.run(["node", "--test", str(ROOT / "tests" / "js" / "plan_view.test.mjs")],
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
