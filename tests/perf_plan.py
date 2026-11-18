"""Manual timing of the update plan (not part of the unit suite — run by hand):

    python tests/perf_plan.py --src Z:\\gog\\_depots --lib Z:\\gogman\\_gog_cache --work E:\\tmp\\perf

Builds a LOCAL mirror of the archive's structure in --work (records, meta and manifests copied; every chunk an
EMPTY file under its real name — the plan only checks that a chunk exists), so lookups run on a local disk the
way they do on the EmuStart server. --src is only read. Results: printed, written to the app log and to
<work>/perf_results.json.

  A  Morrowind (34 347 chunks): lookup of every chunk, all present / all missing, 2, 4, 8 and 16 threads
  B  'Check plan' over 30 archived v2 games, full comparison forced (other build id, same manifests)
  C  first_archive (only shared dependencies looked up) on the real archive for Morrowind and PoP: The Sands of
     Time, against the full lookup measured on 2026-11-18
  D  editions of the same game in the archive: how many chunks they share
"""
import argparse, json, os, re, shutil, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import app  # noqa: E402
import depot_archive as DA  # noqa: E402

WORKERS = (2, 4, 8, 16)
MORROWIND, POP = "1435828767", "1207658747"
FULL_LOOKUP = {MORROWIND: (2874689311, 100641555), POP: (1918513063, 115386169)}   # (download, reused), SMB run
RESULTS: dict = {}


def say(msg: str) -> None:
    print(msg, flush=True)
    app.log(f"[perf plan] {msg}")


def touch_chunks(arc: DA.DepotArchive, md5s) -> int:
    n = 0
    for m in md5s:
        p = arc.chunk_path(m)
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.touch()
            n += 1
    return n


def set_workers(n: int) -> None:
    st = {**app.DEFAULT_SETTINGS, "archive_mode": True, "plan_verify_workers": n, "update_langs": ["en"]}
    app.get_settings = lambda: st


def chunks_of(mans) -> list:
    return sorted({(c.get("compressedMd5") or "").lower() for m in mans for c in DA.manifest_chunks(m)} - {""})


# ── A ────────────────────────────────────────────────────────────────────────────────────────────────────────
def part_a(work: Path) -> None:
    set_workers(4)
    build, meta = app._fetch_build_and_meta(MORROWIND)
    plan = app._plan_archive_scope(meta, MORROWIND, sorted(app._build_lang_set(meta, MORROWIND)), set())
    mans = [app._cdn_depot_manifest(d) for d in plan["depots"]]
    if plan["deps"]:
        mans += [x["man"] for x in app._dependency_manifests(plan["deps"])[0]]
    md5s = chunks_of(mans)
    present, missing = DA.DepotArchive(work / "A_present"), DA.DepotArchive(work / "A_missing")
    present.ensure(); missing.ensure()
    t = time.monotonic()
    made = touch_chunks(present, md5s)
    say(f"A: Morrowind {len(md5s)} chunków; utworzono {made} pustych plików w {time.monotonic() - t:.1f}s")
    res = {}
    for case, arc in (("obecne", present), ("brakujące", missing)):
        for w in WORKERS:
            set_workers(w)
            app._PLAN_POOL["ex"], app._PLAN_POOL["n"] = None, 0
            times = []
            for _ in range(2):                         # 1st = cold-ish, 2nd = warm file system cache
                t = time.monotonic()
                got = app._plan_stat(arc, md5s, app._PlanDeadline(3600))
                times.append(time.monotonic() - t)
            hit = sum(got.values())
            res[f"{case}/{w}"] = times
            say(f"A: {case:9s} {w:2d} wątki: {times[0]:6.2f}s / {times[1]:6.2f}s "
                f"({len(md5s) / times[1]:,.0f} chunków/s), obecnych {hit}")
    RESULTS["A"] = {"chunks": len(md5s), "seconds": res}


# ── B ────────────────────────────────────────────────────────────────────────────────────────────────────────
def part_b(src: DA.DepotArchive, work: Path, n_games: int) -> None:
    local = DA.DepotArchive(work / "B_archive" / "_depots")
    local.ensure()
    recs = sorted((r for r in src.list_records() if r.get("state") == DA.STATE_COMPLETE
                   and (r.get("source") or {}).get("content_system") != 1), key=lambda r: str(r["product_id"]))
    picked, dep_ids, total = [], {}, 0
    for r in recs:
        if len(picked) >= n_games:
            break
        try:
            meta = src.get_meta(r["product_id"], r["build_id"])
            mans = [src.get_manifest("depot", d["manifest"]) for d in r.get("depots") or []]
            deps = [(d["id"], d["manifest"], src.get_manifest("dep", d["manifest"])) for d in r.get("dependencies") or []]
        except DA.ArchiveError:
            continue
        local.put_meta(r["product_id"], r["build_id"], meta)
        for d, m in zip(r.get("depots") or [], mans):
            local.put_manifest("depot", d["manifest"], m)
        for did, mid, m in deps:
            local.put_manifest("dep", mid, m)
            dep_ids[did] = mid
        local.write_record(r)
        total += touch_chunks(local, chunks_of(mans + [m for _, _, m in deps]))
        picked.append(r)
    say(f"B: {len(picked)} gier skopiowanych lokalnie, {total} pustych plików chunków")
    by_pid = {str(r["product_id"]): r for r in picked}
    games = [g for g in app.scan_games() if str(g["product"].get("id") or g["id"]) in by_pid]
    app.BASE = work / "B_archive"
    os.environ["GOGGUI_EXCHANGE_DIR"] = str(work / "B_exchange")
    app.scan_games = lambda: list(games)
    app._owned_ids_cached = lambda max_age=1800: None

    def fake_build(pid):                       # other build id, the same manifests: full comparison, no network
        r = by_pid[str(pid)]
        meta = dict(local.get_meta(pid, r["build_id"]))
        meta["buildId"] = "PERF"
        return {"build_id": "PERF", "version_name": r.get("version_name") or "", "generation": "2"}, meta
    app._fetch_build_and_meta = fake_build
    app._cdn_depot_manifest = lambda d: local.get_manifest("depot", d["manifest"])
    app._dependency_manifests = lambda ids: ([{"id": i, "manifest": dep_ids[i], "man": local.get_manifest("dep", dep_ids[i])}
                                              for i in ids if i in dep_ids], {i for i in ids if i not in dep_ids})
    res = {}
    for w in WORKERS:
        set_workers(w)
        app.get_settings().update(archive_dir="")
        app._PLAN_POOL["ex"], app._PLAN_POOL["n"] = None, 0
        app._PLAN_ALL["cancel"].clear()
        run = app._plan_all_worker(app._plan_all_targets())
        st = json.loads((work / "B_exchange" / "status.json").read_text(encoding="utf-8"))["update_plans"]
        per = sorted(float(s.get("plan_seconds") or 0) for s in st.values())
        res[w] = {"seconds": run["seconds"], "games": run["done"], "checked_chunks": run["checked_chunks"],
                  "max_game": per[-1] if per else 0, "median_game": per[len(per) // 2] if per else 0}
        say(f"B: {w:2d} wątki: {run['done']} gier w {run['seconds']:.1f}s, {run['checked_chunks']} chunków, "
            f"mediana gry {res[w]['median_game']:.2f}s, najdłuższa {res[w]['max_game']:.2f}s, "
            f"stany: {sorted({s.get('ui_state') for s in st.values()})}")
    RESULTS["B"] = res


# ── C ────────────────────────────────────────────────────────────────────────────────────────────────────────
def part_c(src_root: Path, lib: Path, work: Path) -> None:
    app.BASE = src_root.parent
    os.environ["GOGGUI_EXCHANGE_DIR"] = str(work / "C_exchange")
    set_workers(2)
    app._PLAN_POOL["ex"], app._PLAN_POOL["n"] = None, 0
    games = {g["id"]: g for g in app.scan_games()}
    res = {}
    for pid in (MORROWIND, POP):
        t = time.monotonic()
        s = app._plan_and_store(games[pid])
        full = FULL_LOOKUP[pid]
        res[pid] = {"seconds": round(time.monotonic() - t, 2), "checked": s.get("checked_chunks"),
                    "download": s.get("download_bytes"), "reused": s.get("reused_bytes"),
                    "full_download": full[0], "full_reused": full[1]}
        say(f"C: {s.get('title')}: {s.get('ui_state')} w {res[pid]['seconds']}s, sprawdzono {s.get('checked_chunks')} "
            f"chunków; do pobrania {s.get('download_bytes')} (pełne sprawdzenie: {full[0]}), ponownie użyte "
            f"{s.get('reused_bytes')} (pełne: {full[1]}) → " +
            ("ZGODNE" if (s.get("download_bytes"), s.get("reused_bytes")) == full else "RÓŻNICA"))
    RESULTS["C"] = res


# ── D ────────────────────────────────────────────────────────────────────────────────────────────────────────
def part_d(src: DA.DepotArchive) -> None:
    recs = [r for r in src.list_records() if r.get("state") == DA.STATE_COMPLETE]
    key = lambda t: " ".join(re.sub(r"[^a-z0-9 ]", " ", (t or "").lower()).split()[:2])
    groups: dict = {}
    for r in recs:
        groups.setdefault(key(r.get("title")), []).append(r)
    pairs = [g for g in groups.values() if len(g) > 1]
    res = []
    for g in pairs[:12]:
        sets = []
        for r in g:
            try:
                sets.append({(c.get("compressedMd5") or "").lower(): int(c.get("compressedSize") or 0)
                             for c in src.record_chunks(r)})
            except DA.ArchiveError:
                sets.append({})
        a, b = sets[0], sets[1]
        common = set(a) & set(b)
        sb = sum(a[m] for m in common)
        res.append({"titles": [r.get("title") for r in g[:2]], "shared_chunks": len(common),
                    "shared_bytes": sb, "a_bytes": sum(a.values()), "b_bytes": sum(b.values())})
        say(f"D: {g[0].get('title')} ↔ {g[1].get('title')}: wspólne {len(common)} chunków, {sb / 2**20:.0f} MB "
            f"z {sum(a.values()) / 2**20:.0f} / {sum(b.values()) / 2**20:.0f} MB")
    RESULTS["D"] = res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="archive root to read (…\\_depots) — never written")
    ap.add_argument("--lib", required=True, help="the app's _gog_cache with library.pak")
    ap.add_argument("--work", required=True, help="local working dir (mirror, results)")
    ap.add_argument("--games", type=int, default=30)
    ap.add_argument("--parts", default="ABCD")
    a = ap.parse_args()
    work = Path(a.work)
    work.mkdir(parents=True, exist_ok=True)
    app.CACHE = Path(a.lib)
    app.LIBRARY_PAK = app.CACHE / "library.pak"
    src = DA.DepotArchive(Path(a.src))
    say(f"=== pomiar planu: źródło {a.src} (tylko odczyt), kopia lokalna {work} ===")
    real = {k: getattr(app, k) for k in ("_fetch_build_and_meta", "_cdn_depot_manifest", "_dependency_manifests",
                                          "scan_games", "_owned_ids_cached", "BASE")}
    if "A" in a.parts:
        part_a(work)
    if "C" in a.parts:
        part_c(Path(a.src), Path(a.lib), work)
    if "D" in a.parts:
        part_d(src)
    if "B" in a.parts:
        part_b(src, work, a.games)
    for k, v in real.items():
        setattr(app, k, v)
    (work / "perf_results.json").write_text(json.dumps(RESULTS, indent=1, ensure_ascii=False), encoding="utf-8")
    say(f"=== wyniki: {work / 'perf_results.json'} ===")


if __name__ == "__main__":
    main()
