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
re-read and verified (see `verify_record`).

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


class DepotArchive:
    """One archive root. All methods are synchronous and thread-safe for
    distinct chunks (each write is an atomic replace of its own file)."""

    def __init__(self, root: Path):
        self.root = Path(root)

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

    def put_chunk(self, md5: str, data: bytes) -> None:
        if hashlib.md5(data).hexdigest().lower() != md5.lower():
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
        _write_json(self._man_path(kind, mid), strip_secrets(man))

    def get_manifest(self, kind: str, mid: str) -> dict:
        m = _read_json(self._man_path(kind, mid))
        if m is None:
            raise ArchiveError(f"brak manifestu {kind} {mid} w archiwum")
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

    def verify_chunks(self, chunks: list, cancel=None, progress=None) -> dict:
        """Full verification (re-read, MD5, inflate, plain MD5).
        Returns {"missing": [md5…], "corrupt": [md5…], "checked": n}."""
        res = {"missing": [], "corrupt": [], "checked": 0}
        seen = set()
        for c in chunks:
            if cancel is not None and cancel():
                raise ArchiveError("anulowano")
            m = (c.get("compressedMd5") or "").lower()
            if m in seen:
                continue
            seen.add(m)
            prob = self.verify_chunk(c)
            res["checked"] += 1
            if prob == "missing":
                res["missing"].append(m)
            elif prob == "corrupt":
                res["corrupt"].append(m)
            if progress:
                progress(int(c.get("compressedSize") or 0))
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

    def gc(self, removed_records: list | None = None) -> tuple[int, int]:
        """Delete chunk files no remaining record references. Objects shared
        with another game/build/dependency stay. Returns (files, bytes)."""
        refs = self.referenced_chunks()
        n = b = 0
        croot = self.root / "chunks"
        if not croot.is_dir():
            return (0, 0)
        for p in croot.rglob("*"):
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
