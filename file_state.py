"""Remembered state of downloaded files, so a repeated update does not re-hash
or re-download what has not changed (no network, no secrets).

One JSON file maps a path RELATIVE to the downloads directory to:

    {"size": int, "mtime_ns": int,     # the local file when it was last checked
     "md5": "…",                       # its whole-file MD5 at that moment
     "remote": {...} | null}           # what GOG's CDN said about it then
                                       # (ETag / Last-Modified / length)

An entry is trusted only while the file on disk still has the same size and
modification time; anything else — a touched, replaced or truncated file —
falls back to the full check. The module is free of app/webview imports so it
can be unit tested.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

VERSION = 1


class FileState:
    def __init__(self, store: Path, root: Path):
        self.store = Path(store)
        self.root = Path(root)
        self._lock = threading.Lock()
        self._dirty = False
        self._data: dict = {}
        try:
            raw = json.loads(self.store.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and raw.get("version") == VERSION:
                self._data = dict(raw.get("files") or {})
        except (FileNotFoundError, ValueError, OSError):
            self._data = {}

    # ── keys ──────────────────────────────────────────────────────────────
    def _key(self, p: Path) -> str | None:
        try:
            rel = Path(p).resolve().relative_to(self.root.resolve())
        except (ValueError, OSError):
            return None                       # outside the downloads dir: never cached
        k = rel.as_posix()
        return k.lower() if os.name == "nt" else k

    @staticmethod
    def _stat(p: Path):
        try:
            st = Path(p).stat()
        except OSError:
            return None
        return int(st.st_size), int(st.st_mtime_ns)

    def _fresh(self, p: Path) -> dict | None:
        """The entry for `p` if the file is unchanged since it was recorded."""
        k = self._key(p)
        if k is None:
            return None
        with self._lock:
            e = self._data.get(k)
        st = self._stat(p)
        if not e or st is None:
            return None
        if (int(e.get("size", -1)), int(e.get("mtime_ns", -1))) != st:
            return None
        return e

    # ── queries ───────────────────────────────────────────────────────────
    def md5(self, p: Path) -> str | None:
        """Remembered MD5 of an unchanged file, else None (caller hashes it)."""
        e = self._fresh(p)
        return (e or {}).get("md5") or None

    def remote_unchanged(self, p: Path, remote: dict | None) -> bool:
        """True when the local file is unchanged since it was last confirmed
        identical to GOG's copy AND the CDN describes the same object now.
        A signature without a validator (ETag or Last-Modified) never counts."""
        if not remote or not (remote.get("etag") or remote.get("last_modified")):
            return False
        e = self._fresh(p)
        if not e or not e.get("remote"):
            return False
        if remote.get("length") not in (None, "") and int(remote["length"]) != int(e["size"]):
            return False
        return _sig(e["remote"]) == _sig(remote)

    # ── updates ───────────────────────────────────────────────────────────
    def put(self, p: Path, md5: str, remote: dict | None = None) -> None:
        k = self._key(p)
        st = self._stat(p)
        if k is None or st is None:
            return
        with self._lock:
            self._data[k] = {"size": st[0], "mtime_ns": st[1], "md5": str(md5).lower(),
                             "remote": dict(remote) if remote else None}
            self._dirty = True

    def forget_missing(self, folder: Path) -> int:
        """Drop entries under `folder` whose file no longer exists."""
        pre = self._key(folder)
        if pre is None:
            return 0
        pre = pre.rstrip("/") + "/"
        with self._lock:
            gone = [k for k in self._data if k.startswith(pre)
                    and not (self.root / k).exists()]
            for k in gone:
                del self._data[k]
            if gone:
                self._dirty = True
        return len(gone)

    def save(self) -> None:
        with self._lock:
            if not self._dirty:
                return
            blob = json.dumps({"version": VERSION, "files": self._data},
                              ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self._dirty = False
        self.store.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.store.with_name(self.store.name + f".tmp{os.getpid()}")
        tmp.write_bytes(blob)
        os.replace(tmp, self.store)


def _sig(remote: dict) -> tuple:
    return (str(remote.get("etag") or ""), str(remote.get("last_modified") or ""),
            str(remote.get("length") or ""), str(remote.get("name") or ""))
