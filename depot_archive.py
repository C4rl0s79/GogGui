"""Local GOG depot archive — versioned on-disk format (no network, no secrets).

The archive keeps what a Galaxy content-system v2 install needs WITHOUT access
to the GOG CDN: the build meta, the depot manifests, the dependency manifests
and every compressed chunk (exactly the zlib blobs the CDN serves, named by
their compressedMd5). An installer reads a chunk, verifies it, decompresses it
and writes it straight into the game directory.

Layout (all paths relative to the archive root, default <installers>/_depots):

    archive.json                         {"format", "version"} — format marker
    chunks/ab/cd/<compressedMd5>         compressed chunk, content-addressed
                                         (shared by every game/build/dependency)
    manifests/depot/ab/cd/<id>.json      depot manifest (decoded JSON)
    manifests/dep/ab/cd/<id>.json        dependency (redist) depot manifest
    products/<pid>/<build_id>.meta.json  Galaxy build meta (repository manifest)
    products/<pid>/<build_id>.json       archive RECORD: scope, depots, state
    migrations/<pid>.json                per-game migration journal

Nothing in here ever holds tokens, cookies, secure links or account data: the
archive is meant to be shared (EmuStart Server → Lumen). Records are written
atomically; a record is "complete" only after every chunk it references was
fully verified (compressed MD5, inflate, plain MD5) — in memory right after its
download, or by re-reading it (`verify_chunks`).

The module is deliberately free of app/webview imports so it can be unit
tested and later reused by a remote data source.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath

FORMAT = "goggui-depot-archive"
VERSION = 1

STATE_INCOMPLETE = "incomplete"
STATE_COMPLETE = "complete"

# Migration journal phases (per game). The order is the mandatory sequence.
PH_PLANNED = "planned"
PH_DOWNLOADING = "downloading"
PH_VERIFYING = "verifying"
PH_COMMITTED = "committed"         # archive verified + record complete; delete list frozen
PH_CLEANUP = "cleanup"             # deleting the frozen list (may be partial)
PH_CLEANUP_FAILED = "cleanup_failed"
PH_DONE = "done"
PH_SKIPPED = "skipped"           # build not archivable (reason in "error"); installers untouched

PENDING_CLEANUP = (PH_COMMITTED, PH_CLEANUP, PH_CLEANUP_FAILED)

_HEX32 = re.compile(r"^[0-9a-fA-F]{32}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9_.\-]{1,128}$")
_WIN_RESERVED = {"con", "prn", "aux", "nul",
                 *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


class ArchiveError(Exception):
    """Generic archive problem (bad format, missing record, …)."""


class CorruptChunk(ArchiveError):
    """A chunk on disk does not match its name (compressed MD5) or won't inflate."""

    def __init__(self, md5: str, why: str):
        super().__init__(f"uszkodzony chunk {md5[:12]}…: {why}")
        self.md5 = md5


class MissingChunk(ArchiveError):
    def __init__(self, md5: str):
        super().__init__(f"brak chunka {md5[:12]}… w archiwum")
        self.md5 = md5


class UnsafePath(ValueError):
    """A depot path that would land outside the target directory."""


# ── path safety ───────────────────────────────────────────────────────────────

def safe_rel(path: str) -> str:
    """Depot item path → normalised relative POSIX path, or UnsafePath.

    Rejects absolute paths, drive letters / UNC prefixes, '..' components,
    NUL bytes, ADS colons and Windows device names — anything that could
    escape the install directory or hit a device instead of a file."""
    s = str(path or "").replace("\\", "/")
    if "\x00" in s:
        raise UnsafePath(f"NUL w ścieżce: {path!r}")
    # A single leading separator is how some manifests write "relative to the
    # install root" (the old _depot_rel stripped it too); a UNC prefix or a
    # drive letter is a real absolute path.
    if s.startswith("//") or re.match(r"^[A-Za-z]:", s):
        raise UnsafePath(f"ścieżka bezwzględna: {path!r}")
    parts = []
    for p in s.split("/"):
        if p in ("", "."):
            continue
        if p == "..":
            raise UnsafePath(f"'..' w ścieżce: {path!r}")
        if ":" in p:
            raise UnsafePath(f"':' w ścieżce: {path!r}")
        stem = p.split(".")[0].strip().lower()
        if stem in _WIN_RESERVED:
            raise UnsafePath(f"zarezerwowana nazwa: {path!r}")
        parts.append(p)
    if not parts:
        raise UnsafePath(f"pusta ścieżka: {path!r}")
    return "/".join(parts)


def safe_join(root: Path, rel: str) -> Path:
    """root / safe_rel(rel), re-checked after resolution (symlinks, case)."""
    r = safe_rel(rel)
    root_res = Path(root).resolve()
    dest = (root_res / PurePosixPath(r)).resolve()
    try:
        dest.relative_to(root_res)
    except ValueError:
        raise UnsafePath(f"poza katalogiem docelowym: {rel!r}")
    return Path(root) / PurePosixPath(r)


def _check_id(value: str, what: str) -> str:
    v = str(value or "")
    if not _SAFE_ID.match(v):
        raise ArchiveError(f"niepoprawny identyfikator {what}: {value!r}")
    return v


def _fan(h: str) -> str:
    return f"{h[0:2]}/{h[2:4]}/{h}"


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except OSError:
            pass
    os.replace(tmp, path)


def _write_json(path: Path, obj) -> None:
    _atomic_write(path, json.dumps(obj, indent=1, ensure_ascii=False).encode("utf-8"))


def _read_json(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


# Keys that must never be stored in a shareable archive (defence in depth —
# the app never passes them, but a build meta or caller could).
_SECRET_KEYS = {"access_token", "refresh_token", "session_id", "token", "cookie",
                "cookies", "authorization", "secure_link", "securelink", "password"}


def strip_secrets(obj):
    if isinstance(obj, dict):
        return {k: strip_secrets(v) for k, v in obj.items()
                if str(k).lower() not in _SECRET_KEYS}
    if isinstance(obj, list):
        return [strip_secrets(v) for v in obj]
    return obj


def check_chunk_bytes(md5: str, data: bytes, plain_md5: str | None = None,
                      compressed_checked: bool = False) -> None:
    """Full check of chunk bytes already in memory (what verify_chunk does after
    re-reading the file): compressed MD5, inflate, plain MD5. Raises CorruptChunk."""
    if not compressed_checked and hashlib.md5(data).hexdigest().lower() != md5.lower():
        raise CorruptChunk(md5, "MD5 danych się nie zgadza")
    try:
        out = zlib.decompress(data, 15)
    except zlib.error as exc:
        raise CorruptChunk(md5, f"zlib: {exc}")
    if plain_md5 and hashlib.md5(out).hexdigest().lower() != plain_md5.lower():
        raise CorruptChunk(md5, "MD5 po dekompresji się nie zgadza")


def manifest_chunks(man: dict) -> list:
    """Every chunk a decoded depot manifest references (files + its SFC):
    [{"compressedMd5", "compressedSize", "md5", "size"}, …]."""
    out = []
    dep = (man or {}).get("depot") or {}
    for it in dep.get("items") or []:
        if it.get("type") == "DepotFile":
            out.extend(it.get("chunks") or [])
    sfc = dep.get("smallFilesContainer") or {}
    out.extend(sfc.get("chunks") or [])
    return out


# ── Update plan: file-level difference of two depot manifests (no network, no writes) ──

SFC_UNIT = "<smallFilesContainer>"


def _norm_path(p) -> str:
    """Manifest path → comparison key: '/' separators, no leading slash, case-insensitive."""
    return str(p or "").replace("\\", "/").lstrip("/").casefold()


def _cmd5(c: dict) -> str:
    return str(c.get("compressedMd5") or "").lower()


def _item_size(it: dict) -> int:
    if it.get("sfcRef"):
        return int((it["sfcRef"] or {}).get("size") or 0)
    return sum(int(c.get("size") or 0) for c in it.get("chunks") or [])


def _manifest_files(man: dict | None) -> tuple[dict, list]:
    """{key: item} of a manifest's DepotFile items + issues (duplicate paths: the first one is kept)."""
    out, issues = {}, []
    for it in ((man or {}).get("depot") or {}).get("items") or []:
        if it.get("type") != "DepotFile" or not it.get("path"):
            continue
        k = _norm_path(it["path"])
        if k in out:
            issues.append({"path": it["path"], "issue": "duplicate_path"})
            continue
        out[k] = it
    return out, issues


def _sfc_seq(man: dict | None) -> list:
    sfc = ((man or {}).get("depot") or {}).get("smallFilesContainer") or {}
    return [_cmd5(c) for c in sfc.get("chunks") or []]


def diff_manifests(old_manifest: dict | None, new_manifest: dict | None, have=None) -> dict:
    """What moving from `old_manifest` to `new_manifest` (decoded depot manifests) means, file by file.

    Key: the normalised, case-insensitive path. A file is unchanged only when its size, its whole-file MD5
    (compared only when both sides have one) and its full ordered compressedMd5 chunk sequence are equal.
    The same chunks in another order → changed with `layout_changed`. `have(compressedMd5) -> bool` says
    whether a chunk is already available (the app passes the whole archive); default: the old manifest's
    chunks. Per-file `missing_bytes` counts every file separately (a chunk shared by two files counts
    twice); `total_download_bytes` counts each missing compressedMd5 once.

    The small files container (SFC) is the download and comparison unit: a new container sequence means
    the whole container is downloaded, whatever the MD5s of the files inside. Files inside it are the
    reporting unit: changed when the container changed, and when the container is the same but their
    sfcRef differs, the manifest is reported as inconsistent (it cannot be fetched file by file).

    Downloads nothing, writes nothing. A missing new manifest is an error; a missing old one = all added."""
    if new_manifest is None:
        raise ArchiveError("brak nowego manifestu depotu — nie ma z czym porównać")
    old_missing = old_manifest is None
    old_files, old_issues = _manifest_files(old_manifest)
    new_files, new_issues = _manifest_files(new_manifest)
    issues = [{**i, "side": "old"} for i in old_issues] + [{**i, "side": "new"} for i in new_issues]
    if have is None:
        known = {_cmd5(c) for c in manifest_chunks(old_manifest)}
        have = known.__contains__

    sizes: dict = {}                       # compressedMd5 → compressedSize (new side)
    avail_cache: dict = {}

    def available(m: str) -> bool:
        if m not in avail_cache:
            avail_cache[m] = bool(have(m))
        return avail_cache[m]

    to_fetch: set = set()                  # unique missing compressedMd5
    reused: set = set()                    # unique available compressedMd5 of added / changed units

    def account(chunks: list) -> dict:
        n_reused = n_missing = miss_bytes = 0
        for c in chunks:
            m = _cmd5(c)
            sizes[m] = int(c.get("compressedSize") or 0)
            if available(m):
                n_reused += 1
                reused.add(m)
            else:
                n_missing += 1
                miss_bytes += sizes[m]
                to_fetch.add(m)
        return {"reused_chunks": n_reused, "missing_chunks": n_missing, "missing_bytes": miss_bytes}

    # SFC: one unit.
    old_sfc, new_sfc = _sfc_seq(old_manifest), _sfc_seq(new_manifest)
    new_sfc_chunks = (((new_manifest.get("depot") or {}).get("smallFilesContainer") or {}).get("chunks") or [])
    sfc_state = ("absent" if not old_sfc and not new_sfc else "added" if not old_sfc
                 else "removed" if not new_sfc else "unchanged" if old_sfc == new_sfc else "changed")
    sfc = {"path": SFC_UNIT, "state": sfc_state, "chunks": len(new_sfc),
           "reused_chunks": 0, "missing_chunks": 0, "missing_bytes": 0}
    if sfc_state in ("added", "changed"):
        sfc.update(account(new_sfc_chunks))
        sfc["layout_changed"] = (sfc_state == "changed" and sorted(old_sfc) == sorted(new_sfc))
    elif sfc_state == "unchanged":
        sfc.update(account(new_sfc_chunks))          # a lost container chunk is downloaded too

    added, changed, removed, unchanged = [], [], [], []
    for k, it in new_files.items():
        seq = [_cmd5(c) for c in it.get("chunks") or []]
        entry = {"path": it["path"], "size": _item_size(it), "chunks": len(seq)}
        if it.get("sfcRef"):
            entry["sfc"] = True
        old = old_files.get(k)
        if old is None:
            entry.update(account(it.get("chunks") or []) if not it.get("sfcRef")
                         else {"reused_chunks": 0, "missing_chunks": 0, "missing_bytes": 0})
            added.append(entry)
            continue
        oseq = [_cmd5(c) for c in old.get("chunks") or []]
        md5_new, md5_old = str(it.get("md5") or "").lower(), str(old.get("md5") or "").lower()
        md5_same = not (md5_new and md5_old) or md5_new == md5_old
        same_size = _item_size(old) == entry["size"]
        reasons = []
        if it.get("sfcRef") or old.get("sfcRef"):
            nref, oref = dict(it.get("sfcRef") or {}), dict(old.get("sfcRef") or {})
            # merge_manifests tags each file with its own container's id; one manifest has one container
            box_changed = (nref.get("container") != oref.get("container")
                           if "container" in nref and "container" in oref else sfc_state == "changed")
            if bool(it.get("sfcRef")) != bool(old.get("sfcRef")):
                reasons.append("sfc_storage_changed")
            elif box_changed:
                reasons.append("sfc_container_changed")
            elif dict(it.get("sfcRef") or {}) != dict(old.get("sfcRef") or {}) or not same_size or not md5_same:
                reasons.append("sfc_ref_changed")
                entry["manifest_inconsistent"] = True
                issues.append({"path": it["path"], "side": "new", "issue": "sfc_ref_changed_same_container"})
        if seq != oseq:
            reasons.append("chunks")
        if not same_size:
            reasons.append("size")
        if not md5_same:
            reasons.append("md5")
        if not reasons:
            # Same file — its chunks still count: already there = reused; lost from the archive = to download
            # (the update fetches every missing chunk of the build, not only those of changed files).
            if not it.get("sfcRef"):
                acc = account(it.get("chunks") or [])
                if acc["missing_chunks"]:
                    entry.update(acc)
                    issues.append({"path": it["path"], "side": "archive", "issue": "chunk_missing_in_archive"})
            unchanged.append(entry)
            continue
        entry["reasons"] = reasons
        if seq != oseq and sorted(seq) == sorted(oseq):
            entry["layout_changed"] = True
        entry.update(account(it.get("chunks") or []) if not it.get("sfcRef")
                     else {"reused_chunks": 0, "missing_chunks": 0, "missing_bytes": 0})
        changed.append(entry)
    for k, it in old_files.items():
        if k not in new_files:
            removed.append({"path": it["path"], "size": _item_size(it),
                            "chunks": len(it.get("chunks") or []), **({"sfc": True} if it.get("sfcRef") else {})})

    for lst in (added, changed, removed, unchanged):
        lst.sort(key=lambda e: _norm_path(e["path"]))
    return {
        "old_missing": old_missing,
        "added": added, "changed": changed, "removed": removed, "unchanged": unchanged,
        "sfc": sfc,
        "counts": {"added": len(added), "changed": len(changed), "removed": len(removed),
                   "unchanged": len(unchanged)},
        "total_download_bytes": sum(sizes[m] for m in to_fetch),
        "download_chunks": len(to_fetch),
        "reused_bytes": sum(sizes[m] for m in reused),
        "reused_chunk_count": len(reused),
        "issues": issues,
        # compressedMd5 → compressedSize, so several diffs can be totalled without counting a chunk twice
        "download_set": {m: sizes[m] for m in to_fetch},
        "reused_set": {m: sizes[m] for m in reused},
    }


# ── Depot groups: GOG v2 build meta has no depot id or name, and several depots of one build share every
# describing field. Depots are therefore grouped by that FULL key (never matched one-to-one by guess); a group
# is compared as one set of files.

def depot_group_key(d: dict, platform: str, generation) -> dict:
    """The full describing key of a depot entry of a build meta (or a dependency: {"dependency": id})."""
    if d.get("dependency"):
        return {"kind": "dependency", "id": str(d["dependency"])}
    bit = d.get("osBitness")
    return {"kind": "depot", "product_id": str(d.get("productId") or ""),
            "platform": str(platform or ""), "generation": int(generation or 2),
            "languages": sorted({str(x).casefold() for x in d.get("languages") or []}),
            "os_bitness": sorted(str(x) for x in bit) if isinstance(bit, list) else bit,
            "is_gog_depot": d.get("isGogDepot")}


def _key_str(key: dict) -> str:
    return json.dumps(key, sort_keys=True, separators=(",", ":"))


def _item_sig(it: dict):
    return (str(it.get("md5") or "").lower(), tuple(_cmd5(c) for c in it.get("chunks") or []),
            json.dumps(it.get("sfcRef") or {}, sort_keys=True), _item_size(it))


def merge_manifests(manifests: list) -> tuple[dict, list]:
    """Depot manifests of one group → one manifest. Every small files container keeps its identity: a file in
    one gets `sfcRef.container` = the container's id (MD5 of its chunk sequence), and the containers are
    concatenated in id order, so an unchanged container compares equal whatever the depot order. A path in
    two depots with the same content is kept once; with DIFFERENT content it is an `ambiguous_path` issue
    (the first is kept — nothing is guessed). Returns (manifest, issues)."""
    items, issues, containers = {}, [], {}
    for man in manifests:
        dep = (man or {}).get("depot") or {}
        sfc_chunks = (dep.get("smallFilesContainer") or {}).get("chunks") or []
        cid = (hashlib.md5("|".join(_cmd5(c) for c in sfc_chunks).encode()).hexdigest()
               if sfc_chunks else "")
        if cid:
            containers[cid] = sfc_chunks
        for it in dep.get("items") or []:
            if it.get("type") != "DepotFile" or not it.get("path"):
                continue
            it = dict(it)
            if it.get("sfcRef"):
                it["sfcRef"] = {**it["sfcRef"], "container": cid}
            k = _norm_path(it["path"])
            prev = items.get(k)
            if prev is None:
                items[k] = it
            elif _item_sig(prev) != _item_sig(it):
                issues.append({"path": it["path"], "issue": "ambiguous_path"})
    out = {"depot": {"items": list(items.values())}}
    if containers:
        out["depot"]["smallFilesContainer"] = {
            "chunks": [c for cid in sorted(containers) for c in containers[cid]]}
    return out, issues


def diff_depot_groups(old_groups: list, new_groups: list, have=None) -> dict:
    """Compare two builds group by group. `old_groups` / `new_groups`: [(key dict, [manifest, …])]; depots
    with the same key are one group. A group only in the new build = depot_added (all files added), only in
    the old = depot_removed (all files removed). Totals count each missing compressedMd5 once overall."""
    old_by = {}
    for key, mans in old_groups:
        old_by.setdefault(_key_str(key), (key, []))[1].extend(mans)
    new_by = {}
    for key, mans in new_groups:
        new_by.setdefault(_key_str(key), (key, []))[1].extend(mans)
    if have is None:
        known = {_cmd5(c) for _, mans in old_by.values() for m in mans for c in manifest_chunks(m)}
        have = known.__contains__
    groups, dl, reused = [], {}, {}
    counts = {"added": 0, "changed": 0, "removed": 0, "unchanged": 0}
    states = {"depot_added": 0, "depot_removed": 0, "changed": 0, "unchanged": 0}
    issues = []
    for ks in sorted(set(old_by) | set(new_by)):
        key = (new_by.get(ks) or old_by[ks])[0]
        old_m, old_i = merge_manifests(old_by[ks][1]) if ks in old_by else (None, [])
        new_m, new_i = merge_manifests(new_by[ks][1]) if ks in new_by else ({"depot": {"items": []}}, [])
        r = diff_manifests(old_m, new_m, have=have)
        if ks not in old_by:
            state = "depot_added"
        elif ks not in new_by:
            state = "depot_removed"
        elif r["counts"]["added"] or r["counts"]["changed"] or r["counts"]["removed"] or \
                r["sfc"]["state"] in ("added", "changed", "removed"):
            state = "changed"
        else:
            state = "unchanged"
        states[state] += 1
        for k in counts:
            counts[k] += r["counts"][k]
        dl.update(r.pop("download_set"))
        reused.update(r.pop("reused_set"))
        g_issues = ([{**i, "side": "old"} for i in old_i] + [{**i, "side": "new"} for i in new_i]
                    + r.pop("issues"))
        issues.extend({**i, "group": key} for i in g_issues)
        groups.append({"key": key, "state": state, "depots_old": len(old_by.get(ks, (0, []))[1]),
                       "depots_new": len(new_by.get(ks, (0, []))[1]), **r, "issues": g_issues})
    return {"groups": groups, "counts": counts, "group_states": states,
            "total_download_bytes": sum(dl.values()), "download_chunks": len(dl),
            "reused_bytes": sum(reused.values()), "reused_chunk_count": len(reused),
            "issues": issues}


class DepotArchive:
    """One archive root. All methods are synchronous and thread-safe for
    distinct chunks (each write is an atomic replace of its own file)."""

    def __init__(self, root: Path):
        self.root = Path(root)
        # Manifests are immutable per id (content-addressed by GOG): one read
        # per archive instance, however many passes need them. Read-only use.
        self._man_cache: dict = {}

    # ── format marker ─────────────────────────────────────────────────────
    def ensure(self) -> None:
        marker = self.root / "archive.json"
        cur = _read_json(marker)
        if cur is None:
            _write_json(marker, {"format": FORMAT, "version": VERSION,
                                 "created": time.strftime("%Y-%m-%dT%H:%M:%S")})
            return
        if cur.get("format") != FORMAT:
            raise ArchiveError(f"{marker}: obcy format {cur.get('format')!r}")
        if int(cur.get("version") or 0) > VERSION:
            raise ArchiveError(f"{marker}: wersja {cur.get('version')} nowsza niż "
                               f"obsługiwana ({VERSION}) — zaktualizuj program")

    def exists(self) -> bool:
        return (self.root / "archive.json").exists()

    # ── chunks ────────────────────────────────────────────────────────────
    def chunk_path(self, md5: str) -> Path:
        if not _HEX32.match(str(md5 or "")):
            raise ArchiveError(f"niepoprawny identyfikator chunka: {md5!r}")
        return self.root / "chunks" / _fan(md5.lower())

    def has_chunk(self, md5: str, compressed_size: int | None = None) -> bool:
        p = self.chunk_path(md5)
        try:
            st = p.stat()
        except FileNotFoundError:
            return False
        return not compressed_size or st.st_size == int(compressed_size)

    def put_chunk(self, md5: str, data: bytes, verified: bool = False) -> None:
        """`verified=True`: the caller already checked the compressed MD5 of
        exactly these bytes (the downloader does) — don't hash them twice."""
        if not verified and hashlib.md5(data).hexdigest().lower() != md5.lower():
            raise CorruptChunk(md5, "MD5 pobranych danych się nie zgadza")
        _atomic_write(self.chunk_path(md5), data)

    def read_chunk(self, md5: str) -> bytes:
        """Compressed bytes, verified against the name."""
        p = self.chunk_path(md5)
        try:
            data = p.read_bytes()
        except FileNotFoundError:
            raise MissingChunk(md5)
        if hashlib.md5(data).hexdigest().lower() != md5.lower():
            raise CorruptChunk(md5, "MD5 pliku się nie zgadza")
        return data

    def read_chunk_plain(self, md5: str, plain_md5: str | None = None) -> bytes:
        data = self.read_chunk(md5)
        try:
            out = zlib.decompress(data, 15)
        except zlib.error as exc:
            raise CorruptChunk(md5, f"zlib: {exc}")
        if plain_md5 and hashlib.md5(out).hexdigest().lower() != plain_md5.lower():
            raise CorruptChunk(md5, "MD5 po dekompresji się nie zgadza")
        return out

    def verify_chunk(self, c: dict) -> str | None:
        """None if the chunk is present and sound, else a short problem string."""
        md5 = c.get("compressedMd5") or ""
        try:
            self.read_chunk_plain(md5, c.get("md5"))
            return None
        except MissingChunk:
            return "missing"
        except CorruptChunk:
            return "corrupt"

    # ── manifests ─────────────────────────────────────────────────────────
    def _man_path(self, kind: str, mid: str) -> Path:
        if kind not in ("depot", "dep"):
            raise ArchiveError(f"zły rodzaj manifestu {kind!r}")
        mid = _check_id(mid, "manifestu")
        if len(mid) < 4:
            raise ArchiveError(f"za krótki identyfikator manifestu: {mid!r}")
        return self.root / "manifests" / kind / f"{_fan(mid)}.json"

    def has_manifest(self, kind: str, mid: str) -> bool:
        return self._man_path(kind, mid).exists()

    def put_manifest(self, kind: str, mid: str, man: dict) -> None:
        clean = strip_secrets(man)
        _write_json(self._man_path(kind, mid), clean)
        self._man_cache[(kind, str(mid))] = clean

    def get_manifest(self, kind: str, mid: str) -> dict:
        key = (kind, str(mid))
        m = self._man_cache.get(key)
        if m is not None:
            return m
        m = _read_json(self._man_path(kind, mid))
        if m is None:
            raise ArchiveError(f"brak manifestu {kind} {mid} w archiwum")
        self._man_cache[key] = m
        return m

    # ── build meta + records ──────────────────────────────────────────────
    def _rec_path(self, pid: str, build_id: str, suffix: str = ".json") -> Path:
        return (self.root / "products" / _check_id(pid, "produktu")
                / f"{_check_id(build_id, 'buildu')}{suffix}")

    def put_meta(self, pid: str, build_id: str, meta: dict) -> None:
        _write_json(self._rec_path(pid, build_id, ".meta.json"), strip_secrets(meta))

    def get_meta(self, pid: str, build_id: str) -> dict:
        m = _read_json(self._rec_path(pid, build_id, ".meta.json"))
        if m is None:
            raise ArchiveError(f"brak meta buildu {build_id}")
        return m

    def write_record(self, rec: dict) -> None:
        rec = strip_secrets(dict(rec))
        rec["format"], rec["version"] = FORMAT, VERSION
        _write_json(self._rec_path(rec["product_id"], rec["build_id"]), rec)

    def read_record(self, pid: str, build_id: str) -> dict | None:
        return _read_json(self._rec_path(pid, build_id))

    def list_records(self, pid: str | None = None) -> list:
        base = self.root / "products"
        if not base.is_dir():
            return []
        dirs = [base / str(pid)] if pid else [d for d in base.iterdir() if d.is_dir()]
        out = []
        for d in dirs:
            if not d.is_dir():
                continue
            for f in sorted(d.glob("*.json")):
                if f.name.endswith(".meta.json"):
                    continue
                rec = _read_json(f)
                if isinstance(rec, dict) and rec.get("format") == FORMAT:
                    out.append(rec)
        out.sort(key=lambda r: str(r.get("created") or ""), reverse=True)
        return out

    def remove_record(self, pid: str, build_id: str) -> None:
        for suf in (".json", ".meta.json"):
            try:
                self._rec_path(pid, build_id, suf).unlink()
            except FileNotFoundError:
                pass

    # ── referenced objects / verification / GC ────────────────────────────
    def record_chunks(self, rec: dict) -> list:
        """All chunks a record needs (its depots + dependencies)."""
        out = []
        for d in rec.get("depots") or []:
            out.extend(manifest_chunks(self.get_manifest("depot", d["manifest"])))
        for d in rec.get("dependencies") or []:
            out.extend(manifest_chunks(self.get_manifest("dep", d["manifest"])))
        return out

    def missing_chunks(self, chunks: list) -> list:
        seen, out = set(), []
        for c in chunks:
            m = (c.get("compressedMd5") or "").lower()
            if m in seen:
                continue
            seen.add(m)
            if not self.has_chunk(m, c.get("compressedSize")):
                out.append(c)
        return out

    def verify_chunks(self, chunks: list, cancel=None, progress=None, workers: int = 1) -> dict:
        """Full verification (re-read, MD5, inflate, plain MD5).
        `workers` > 1 checks chunks in parallel (hashlib and zlib release the
        GIL on large buffers). Returns {"missing": [md5…], "corrupt": [md5…],
        "checked": n} — lists in input order."""
        uniq, seen = [], set()
        for c in chunks:
            m = (c.get("compressedMd5") or "").lower()
            if m not in seen:
                seen.add(m)
                uniq.append((m, c))

        def one(item):
            if cancel is not None and cancel():
                raise ArchiveError("anulowano")
            m, c = item
            prob = self.verify_chunk(c)
            if progress:
                progress(int(c.get("compressedSize") or 0))
            return m, prob

        if workers > 1 and len(uniq) > 1:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                results = list(ex.map(one, uniq))
        else:
            results = [one(it) for it in uniq]
        res = {"missing": [], "corrupt": [], "checked": len(results)}
        for m, prob in results:
            if prob == "missing":
                res["missing"].append(m)
            elif prob == "corrupt":
                res["corrupt"].append(m)
        return res

    def referenced_chunks(self, exclude: set | None = None) -> set:
        """compressedMd5 of every chunk referenced by any record not in
        `exclude` ({(pid, build_id)}). A manifest that cannot be read makes
        the call fail — GC must never run on a partial reference set."""
        refs = set()
        for rec in self.list_records():
            if exclude and (str(rec["product_id"]), str(rec["build_id"])) in exclude:
                continue
            for c in self.record_chunks(rec):
                refs.add((c.get("compressedMd5") or "").lower())
        return refs

    def gc(self, candidates: set | None = None) -> tuple[int, int]:
        """Delete chunk files no remaining record references. Objects shared
        with another game/build/dependency stay. Returns (files, bytes).

        `candidates` (compressedMd5 set — e.g. the chunks of records just
        removed) limits the sweep to those files instead of walking the whole
        chunk tree; None = full sweep (also clears leftovers of aborted runs)."""
        refs = self.referenced_chunks()
        n = b = 0
        croot = self.root / "chunks"
        if not croot.is_dir():
            return (0, 0)
        if candidates is None:
            paths = croot.rglob("*")
        else:
            paths = (self.chunk_path(m) for m in sorted({str(x).lower() for x in candidates})
                     if _HEX32.match(str(m)))
        for p in paths:
            if not p.is_file() or not _HEX32.match(p.name):
                continue
            if p.name.lower() in refs:
                continue
            try:
                sz = p.stat().st_size
                p.unlink()
                n += 1
                b += sz
            except OSError:
                pass
        return (n, b)

    # ── migration journal ────────────────────────────────────────────────
    def _journal_path(self, pid: str) -> Path:
        return self.root / "migrations" / f"{_check_id(pid, 'produktu')}.json"

    def read_journal(self, pid: str) -> dict | None:
        return _read_json(self._journal_path(pid))

    def write_journal(self, pid: str, j: dict) -> None:
        j = dict(j)
        j["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        _write_json(self._journal_path(pid), strip_secrets(j))

    def list_journals(self) -> list:
        d = self.root / "migrations"
        if not d.is_dir():
            return []
        out = []
        for f in sorted(d.glob("*.json")):
            j = _read_json(f)
            if isinstance(j, dict):
                out.append(j)
        return out

    def pending_cleanups(self) -> list:
        return [j for j in self.list_journals() if j.get("phase") in PENDING_CLEANUP]


def record_scope_covers(rec: dict, langs, dlcs) -> tuple[bool, list]:
    """Does a record's archived scope include the requested languages/DLC?
    Returns (ok, [human-readable gaps])."""
    scope = (rec or {}).get("scope") or {}
    have_l = {str(x).lower() for x in scope.get("languages") or []}
    have_d = {str(x) for x in scope.get("dlcs") or []}
    gaps = []
    for lang in langs or []:
        if str(lang).lower() not in have_l:
            gaps.append(f"język {lang}")
    for d in dlcs or []:
        if str(d) not in have_d:
            gaps.append(f"DLC {d}")
    return (not gaps, gaps)
