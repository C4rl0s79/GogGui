import json, os, re, shutil, sqlite3, subprocess, threading, base64, zlib
import sys
import urllib.request, urllib.error, urllib.parse
import hashlib, time, webbrowser, queue
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import webview


def _base_dirs():
    """Split writable state from read-only bundled assets so a PyInstaller build
    works. When frozen, __file__ points inside the temporary _MEIPASS extraction
    dir (deleted on exit) — writing state there would lose everything each run, so
    state lives next to the .exe while assets are read from the bundle."""
    if getattr(sys, "frozen", False):
        app = Path(sys.executable).resolve().parent          # persistent, next to exe
        res = Path(getattr(sys, "_MEIPASS", app))            # bundled resources
    else:
        app = Path(__file__).resolve().parent
        res = app
    return app, res


APP_VERSION = "1.3.0"      # see CHANGELOG.md

APP_DIR, RESOURCE_DIR = _base_dirs()
# Portable app state — ALWAYS inside the program directory (next to the exe):
CACHE       = APP_DIR / "_gog_cache"       # index, secrets, packed library (never moves)
INDEX       = CACHE / "index.sqlite"
LIBRARY_PAK = CACHE / "library.pak"        # all product/details JSON, packed (zstd→lzma)
GOG_TOKENS_FILE = CACHE / "gog_tokens.json"
SECRETS_FILE    = CACHE / "secrets.json"   # SGDB key etc., encrypted at rest
ART_FILE        = CACHE / "art.json"        # per-game hero/logo choices (auto + pinned)
JSON_DIR   = APP_DIR / "json"              # legacy per-slug JSON (auto-migrated into LIBRARY_PAK)
HTML       = RESOURCE_DIR / "assets" / "index.html"   # read-only, from the bundle
# User content — configurable AND portable (created under APP_DIR if missing):
BASE       = Path(r"D:\GOGinstall")        # installer download directory
GOG_GAMES  = Path(r"C:\GOG Games")         # installed games directory

PRODUCT_RE     = re.compile(r"^product_(.+)\.json$", re.I)
INSTALLER_EXTS = ("*.exe", "*.sh", "*.bin", "*.dmg", "*.pkg")

# Read lgogdownloader's stored Galaxy token out of WSL — used ONLY for one-time
# migration of an existing login into the app's own encrypted store.
GALAXY_TOKENS_CAT = ["wsl", "bash", "-c", 'cat "$HOME/.config/lgogdownloader/galaxy_tokens.json"']

# Owned-games list straight from the GOG account API (fresh, includes NEW games).
GOG_OWNED_API = "https://embed.gog.com/user/data/games"

# Token refresh — public GOG Galaxy client credentials (same ones lgogdownloader
# ships with; these are not secret).
GOG_AUTH_TOKEN_URL = "https://auth.gog.com/token"
GOG_AUTH_PAGE      = "https://auth.gog.com/auth"
GOG_REDIRECT       = "https://embed.gog.com/on_login_success?origin=client"
GOG_CLIENT_ID       = "46899977096215655"
GOG_CLIENT_SECRET   = "9d85c43b1482497dbbce61f6e4aa173a433796eeae2ca8c5f6129f2dc4de46d9"

# Connection budget (parallel files AND single-file segments share this).
_CONN_MIN, _CONN_MAX, _CONN_DEFAULT = 1, 6, 4
# Only segment a single file when it is at least this big.
_SEGMENT_MIN_BYTES = 50 * 1024 * 1024

# Public GOG v2 games API — crisp Galaxy artwork (hero background, box art).
GOG_V2_GAMES_API = "https://api.gog.com/v2/games/{id}?locale=en-US"

# Public GOG products API — full product JSON (images, languages, compat, …),
# no auth and no installer download required.
GOG_PRODUCT_API = (
    "https://api.gog.com/products/{id}"
    "?expand=downloads,expanded_dlcs,description,screenshots,videos,"
    "related_products,changelog&locale=en-US"
)
_GOG_FETCH_WORKERS = 8

# ── Galaxy content-system v2 (depot install — no offline installer) ──────────
GOG_CONTENT_SYSTEM = "https://content-system.gog.com"
GOG_CDN            = "https://gog-cdn-fastly.gog.com"
GOG_BUILDS_API     = GOG_CONTENT_SYSTEM + "/products/{id}/os/windows/builds?generation=2"
GOG_SECURE_LINK    = GOG_CONTENT_SYSTEM + "/products/{id}/secure_link?_version=2&generation=2&path=/"
# Redist dependencies (DOSBox, ScummVM, VC++ …) live in a shared repository and a
# public store CDN — no product-scoped auth is needed to download their chunks.
GOG_DEP_REPO       = GOG_CONTENT_SYSTEM + "/dependencies/repository?generation=2"
GOG_DEP_STORE_LINK = GOG_CONTENT_SYSTEM + "/open_link?generation=2&_version=2&path=/dependencies/store/"
# Marker file with per-build install/resume state inside the game directory.
_DEPOT_STATE_NAME  = "_goginstall_state.json"

# ── streaming state ───────────────────────────────────────────────────────────
_current_proc: subprocess.Popen | None = None
_is_running = False
_proc_lock  = threading.Lock()
_cancel     = threading.Event()   # set by kill_command to stop pure-Python downloads

# Sequential task queue (downloads / installs). While one job runs, further
# queueable jobs wait here and start automatically when the current one ends.
from collections import deque
_task_queue: deque = deque()      # items: {"id", "label", "target"}
_task_seq   = 0
_current_label = ""

# Strip all ANSI escape sequences from raw bytes
_RE_ANSI     = re.compile(rb'\x1b\[[0-9;]*[A-Za-z]')

# ── settings ───────────────────────────────────────────────────────────────────
SETTINGS_FILE = APP_DIR / "settings.json"

DEFAULT_SETTINGS: dict = {
    "--desc-bg":     "#f5f2ee",   # description area background
    "--desc-text":   "#2c2a28",   # description text colour
    "--accent":      "#4f98a3",   # accent / progress bar colour
    "--fs-list":     "12px",      # game-list font size
    "--fs-desc":     "13px",      # description font size
    "--fs-progress": "13px",      # progress-bar label font size
    "--fs-meta":     "11px",      # metadata / small text font size
    "--bar-height":  "8px",       # progress-bar track height
    "download_threads": _CONN_DEFAULT,   # parallel connections budget (1–6)
    "extras_subdir": True,               # put bonus content into <game>/extras/
    "update_langs": ["en", "pl"],        # languages the installer-updater keeps (os = windows)
    "depot_langs":  ["en"],              # default languages for depot install (prefix match)
    # Persisted directories ("" = use the built-in defaults above)
    "json_dir":    "",
    "install_dir": "",
    "games_dir":   "",
    "lang":        "pl",      # UI language (pl / en)
    "theme":       "steam",   # steam | amoled
    "sgdb_key":    "",        # SteamGridDB API key (better hero/logo art)
    "art_hero_source": "gog",  # hero background source: gog | sgdb
    "art_logo_source": "sgdb", # title logo source:      gog | sgdb
    "onboarded":   False,     # first-run wizard completed
}


def get_download_threads() -> int:
    try:
        n = int(get_settings().get("download_threads", _CONN_DEFAULT))
    except Exception:
        n = _CONN_DEFAULT
    return max(_CONN_MIN, min(_CONN_MAX, n))


def get_settings() -> dict:
    saved = {}
    if SETTINGS_FILE.exists():
        try:
            saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            saved = {}
    # One-time migration: move a legacy plaintext SGDB key into encrypted secrets.
    if saved.get("sgdb_key"):
        try:
            _set_secret("sgdb_key", str(saved["sgdb_key"]))
            saved.pop("sgdb_key", None)
            SETTINGS_FILE.write_text(json.dumps(saved, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            log(f"sgdb key migration: {exc}")
    out = {**DEFAULT_SETTINGS, **saved}
    out["sgdb_key"] = ""                                  # never expose the real key
    out["sgdb_key_set"] = bool(_get_secret("sgdb_key"))   # UI hint only
    return out


def save_settings(settings: dict) -> dict:
    try:
        s = dict(settings or {})
        # The SGDB key is a secret: route it to the encrypted store, never to
        # settings.json. An empty value means "leave the existing key unchanged".
        if "sgdb_key" in s:
            val = (s.pop("sgdb_key") or "").strip()
            if val:
                _set_secret("sgdb_key", val)
        s.pop("sgdb_key_set", None)
        disk = {}
        if SETTINGS_FILE.exists():
            try: disk = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            except Exception: disk = {}
        merged = {**disk, **s}
        merged.pop("sgdb_key", None)                       # keep plaintext out of the file
        merged.pop("sgdb_key_set", None)
        SETTINGS_FILE.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _persist_dir(key: str, value: str) -> None:
    """Remember a chosen directory in settings.json (survives restarts)."""
    save_settings({key: value})


def _apply_dir_settings() -> None:
    """On startup: CACHE / library / secrets stay in the program dir (never move).
    BASE (installers) and GOG_GAMES (installed) come from settings, but if the
    target doesn't exist we fall back to a folder inside the program dir, so a
    freshly-copied portable install just works."""
    global BASE, GOG_GAMES
    st = get_settings()
    if st.get("install_dir"):
        BASE = Path(st["install_dir"])
    if st.get("games_dir"):
        GOG_GAMES = Path(st["games_dir"])
    # Portability: create missing user-content dirs under the program directory.
    if not BASE.exists():
        BASE = APP_DIR / "GOGinstall"
    if not GOG_GAMES.exists():
        GOG_GAMES = APP_DIR / "GOG Games"
    try:
        BASE.mkdir(parents=True, exist_ok=True)
        GOG_GAMES.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        log(f"portable dir create: {exc}")
    log(f"dirs: cache={CACHE} install={BASE} games={GOG_GAMES}")


LOG_FILE = APP_DIR / "gog_manager.log"
_LOG_LOCK = threading.Lock()


def log(msg: str) -> None:
    # In a --windowed exe there is no console; print may fail and is invisible.
    # Mirror to a log file next to the exe so diagnostics (e.g. the TPM self-test)
    # are recoverable.
    try:
        print(msg, flush=True)
    except Exception:
        pass
    try:
        with _LOG_LOCK:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except Exception:
        pass


def _send_js(data: dict) -> None:
    """Send a structured message to the JS handleActivity function."""
    payload = json.dumps(data)
    try:
        if webview.windows:
            webview.windows[0].evaluate_js(f"window.handleActivity?.({payload})")
    except Exception as exc:
        log(f"[send_js error] {exc}")


def _push_log(text: str) -> None:
    """Send a plain log/info line to the JS log area."""
    log(text)
    _send_js({"type": "log", "text": text})


# Keep old name as alias so call-sites inside worker() don't need changing
_push_terminal = _push_log


# ── helpers ────────────────────────────────────────────────────────────────────
def ensure_dirs() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)


def norm_url(url) -> str:
    if not url:
        return ""
    return f"https:{url}" if isinstance(url, str) and url.startswith("//") else url


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None                      # optional files (e.g. game-details.json) — no noise
    except Exception as exc:
        log(f"JSON read error: {path} :: {exc}")
        return None


def is_product_json(p: Path) -> bool:
    n = p.name.lower()
    return n.startswith("product_") and n.endswith(".json")


# ══════════════════════════════════════════════════════════════════════════════
#  PACKED STORAGE  (compression + single-file library + encrypted secrets)
#  Everything here lives inside the program directory (CACHE) so the whole app is
#  portable: copy the folder and your GOG cache / library / secrets travel with it.
# ══════════════════════════════════════════════════════════════════════════════

# Prefer zstd (Python 3.14 stdlib `compression.zstd`, or the `zstandard`/`pyzstd`
# packages); fall back to lzma (stdlib) so the store is always readable/writable.
_ZSTD = None
try:
    from compression import zstd as _ZSTD          # Python 3.14+ stdlib
except Exception:
    try:
        import zstandard as _zstd_pkg              # 3rd-party
        class _ZstdShim:
            @staticmethod
            def compress(data, level=10):
                return _zstd_pkg.ZstdCompressor(level=level).compress(data)
            @staticmethod
            def decompress(data):
                return _zstd_pkg.ZstdDecompressor().decompress(data)
        _ZSTD = _ZstdShim
    except Exception:
        _ZSTD = None
import lzma as _lzma

_PACK_MAGIC = b"GLP1"          # GOG Library Pack v1


def _pack(raw: bytes) -> bytes:
    """Compress bytes with a self-describing header so the codec is known on read."""
    if _ZSTD is not None:
        try:
            return _PACK_MAGIC + b"Z" + _ZSTD.compress(raw, 10)
        except Exception as exc:
            log(f"zstd compress failed, using lzma: {exc}")
    return _PACK_MAGIC + b"X" + _lzma.compress(raw, preset=6)


def _unpack(blob: bytes) -> bytes:
    if blob[:4] != _PACK_MAGIC:
        # Unheadered payload: assume raw JSON bytes (defensive).
        return blob
    tag, body = blob[4:5], blob[5:]
    if tag == b"Z":
        if _ZSTD is None:
            raise RuntimeError("Plik spakowany zstd, ale zstd niedostępny w tym Pythonie.")
        return _ZSTD.decompress(body)
    return _lzma.decompress(body)


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


# ── library: {slug: {"product": {...}, "details": {...}}} kept in one packed file
_LIB: dict | None = None
_LIB_LOCK = threading.Lock()


def _lib_load() -> dict:
    """Load the packed library into memory (once). On first run, migrate any legacy
    per-slug JSON files from JSON_DIR into the pack, then use the pack from then on."""
    global _LIB
    if _LIB is not None:
        return _LIB
    with _LIB_LOCK:
        if _LIB is not None:
            return _LIB
        data = {}
        if LIBRARY_PAK.exists():
            try:
                data = json.loads(_unpack(LIBRARY_PAK.read_bytes()).decode("utf-8"))
            except Exception as exc:
                log(f"library.pak read failed: {exc}")
                data = {}
        else:
            data = _migrate_json_dir()
            if data:
                _lib_save(data)
        _LIB = data
        return _LIB


def _migrate_json_dir() -> dict:
    """One-time import of legacy JSON_DIR/<slug>/product_<slug>.json (+ game-details)."""
    out = {}
    if not JSON_DIR.exists():
        return out
    n = 0
    for p in JSON_DIR.rglob("*.json"):
        if not is_product_json(p):
            continue
        m = PRODUCT_RE.match(p.name)
        if not m:
            continue
        prod = read_json(p)
        if not prod:
            continue
        slug = prod.get("slug") or m.group(1)
        det  = read_json(p.with_name("game-details.json")) or {}
        out[slug] = {"product": prod, "details": det, "key": m.group(1)}
        n += 1
    if n:
        log(f"migrated {n} legacy JSON files into library.pak")
    return out


def _lib_save(data: dict | None = None) -> None:
    global _LIB
    if data is None:
        data = _LIB or {}
    raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
    _atomic_write(LIBRARY_PAK, _pack(raw))
    _LIB = data


def _lib_all() -> dict:
    return _lib_load()


def _lib_put(slug: str, product: dict, details: dict | None = None,
             key: str | None = None) -> None:
    lib = _lib_load()
    with _LIB_LOCK:
        entry = lib.get(slug) or {}
        entry["product"] = product
        if details is not None:
            entry["details"] = details
        entry.setdefault("details", {})
        entry["key"] = key or entry.get("key") or slug
        lib[slug] = entry
        _lib_save(lib)


def _lib_put_many(items: list) -> int:
    """Bulk insert [(slug, product[, rating]), …] with one pack rewrite (fast
    sync). `rating` (optional) is GOG's {value, count} kept on the entry."""
    lib = _lib_load()
    with _LIB_LOCK:
        n = 0
        for item in items:
            slug, product = item[0], item[1]
            rating = item[2] if len(item) > 2 else None
            s = product.get("slug") or slug
            entry = lib.get(s) or {}
            entry["product"] = product
            entry.setdefault("details", {})
            entry["key"] = entry.get("key") or s
            if rating is not None:
                entry["rating"] = rating
            lib[s] = entry
            n += 1
        _lib_save(lib)
        return n


# ── secrets: SGDB key etc., encrypted at rest (same DPAPI path as GOG tokens) ──
# ── secrets: SGDB key etc., encrypted at rest ────────────────────────────────
# Backend chain, best first:
#   1. TPM  — a non-exportable RSA key inside the TPM 2.0 chip (CNG "Microsoft
#      Platform Crypto Provider"). Even with the whole disk + your Windows password
#      an attacker can't decrypt offline without THIS machine's TPM. Copying the
#      folder to another PC → the key can't be unwrapped → the app asks you to
#      re-enter it (portable-but-safe).
#   2. DPAPI — user+machine bound (master key lives in your profile).
#   3. XOR   — non-Windows obfuscation only (documented as not real encryption).
_TPM_KEY_NAME = "GOGLibraryManager_SecretsKey_v1"
_TPM_OK: bool | None = None      # self-test result, cached for the session


def _tpm_handles():
    """Open the TPM provider and open-or-create our persisted, non-exportable key.
    Returns (ncrypt, hProvider, hKey) or raises. Windows-only."""
    import ctypes
    from ctypes import wintypes
    ncrypt = ctypes.windll.ncrypt
    SILENT = 0x00000040
    NTE_EXISTS = 0x8009000F
    hProv = wintypes.HANDLE()
    if ncrypt.NCryptOpenStorageProvider(ctypes.byref(hProv),
            ctypes.c_wchar_p("Microsoft Platform Crypto Provider"), 0) != 0:
        raise OSError("no platform crypto provider (TPM)")
    hKey = wintypes.HANDLE()
    st = ncrypt.NCryptOpenKey(hProv, ctypes.byref(hKey),
                              ctypes.c_wchar_p(_TPM_KEY_NAME), 0, SILENT)
    if st != 0:
        # Create it once (RSA-2048, non-exportable is the TPM default).
        st = ncrypt.NCryptCreatePersistedKey(hProv, ctypes.byref(hKey),
                 ctypes.c_wchar_p("RSA"), ctypes.c_wchar_p(_TPM_KEY_NAME), 0, 0)
        if st != 0:
            ncrypt.NCryptFreeObject(hProv)
            raise OSError(f"NCryptCreatePersistedKey failed: {st & 0xFFFFFFFF:#x}")
        length = ctypes.c_ulong(2048)
        ncrypt.NCryptSetProperty(hKey, ctypes.c_wchar_p("Length"),
                                 ctypes.byref(length), ctypes.sizeof(length), 0)
        if ncrypt.NCryptFinalizeKey(hKey, 0) != 0:
            ncrypt.NCryptFreeObject(hKey); ncrypt.NCryptFreeObject(hProv)
            raise OSError("NCryptFinalizeKey failed")
    return ncrypt, hProv, hKey


def _oaep_pad():
    import ctypes

    class BCRYPT_OAEP_PADDING_INFO(ctypes.Structure):
        _fields_ = [("pszAlgId", ctypes.c_wchar_p),
                    ("pbLabel", ctypes.c_void_p),
                    ("cbLabel", ctypes.c_ulong)]
    return BCRYPT_OAEP_PADDING_INFO("SHA256", None, 0)


def _tpm_wrap(raw: bytes) -> bytes | None:
    """RSA-OAEP-encrypt small data with the TPM key. Fits ~190 bytes (RSA-2048)."""
    try:
        import ctypes
        NCRYPT_PAD_OAEP = 0x00000004
        ncrypt, hProv, hKey = _tpm_handles()
        try:
            pad = _oaep_pad()
            cb = ctypes.c_ulong(0)
            if ncrypt.NCryptEncrypt(hKey, raw, len(raw), ctypes.byref(pad),
                                    None, 0, ctypes.byref(cb), NCRYPT_PAD_OAEP) != 0:
                return None
            buf = ctypes.create_string_buffer(cb.value)
            if ncrypt.NCryptEncrypt(hKey, raw, len(raw), ctypes.byref(pad),
                                    buf, cb.value, ctypes.byref(cb), NCRYPT_PAD_OAEP) != 0:
                return None
            return buf.raw[:cb.value]
        finally:
            ncrypt.NCryptFreeObject(hKey); ncrypt.NCryptFreeObject(hProv)
    except Exception as exc:
        log(f"tpm wrap failed: {exc}")
        return None


def _tpm_unwrap(blob: bytes) -> bytes | None:
    try:
        import ctypes
        NCRYPT_PAD_OAEP = 0x00000004
        ncrypt, hProv, hKey = _tpm_handles()
        try:
            pad = _oaep_pad()
            cb = ctypes.c_ulong(0)
            if ncrypt.NCryptDecrypt(hKey, blob, len(blob), ctypes.byref(pad),
                                    None, 0, ctypes.byref(cb), NCRYPT_PAD_OAEP) != 0:
                return None
            buf = ctypes.create_string_buffer(cb.value)
            if ncrypt.NCryptDecrypt(hKey, blob, len(blob), ctypes.byref(pad),
                                    buf, cb.value, ctypes.byref(cb), NCRYPT_PAD_OAEP) != 0:
                return None
            return buf.raw[:cb.value]
        finally:
            ncrypt.NCryptFreeObject(hKey); ncrypt.NCryptFreeObject(hProv)
    except Exception as exc:
        log(f"tpm unwrap failed: {exc}")
        return None


def _tpm_selftest() -> bool:
    """Round-trip a random token through the TPM before ever relying on it. If the
    machine has no usable TPM (or the CNG calls misbehave), we permanently fall
    back to DPAPI for this session — so a TPM problem never breaks the app."""
    global _TPM_OK
    if _TPM_OK is not None:
        return _TPM_OK
    _TPM_OK = False
    if os.name == "nt":
        try:
            token = b"tpm-selftest-" + os.urandom(8)
            wrapped = _tpm_wrap(token)
            ok = bool(wrapped) and _tpm_unwrap(wrapped) == token
            # Also verify the hybrid path (used for large secrets like GOG tokens),
            # but don't require it — direct TPM alone still counts as available.
            if ok and _AESGCM is not None:
                big = os.urandom(1500)
                hb = _seal_hybrid(big)
                if hb is None or _open_hybrid(hb) != big:
                    log("TPM hybrid selftest failed — large secrets will use DPAPI")
            _TPM_OK = ok
            log(f"TPM secrets backend: {'available' if _TPM_OK else 'unavailable, using DPAPI'}")
        except Exception as exc:
            log(f"TPM selftest error: {exc}")
            _TPM_OK = False
    return _TPM_OK


# ── unified secrets store: ONE data.json holds every secret, each namespace
#    sealed independently with the best backend for its size:
#      • sgdb  (tiny)  → TPM (RSA-OAEP fits) → DPAPI → XOR
#      • tokens (large)→ DPAPI (RSA-OAEP too small for JWTs) → XOR
#    Replaces the old gog_tokens.json + secrets.json (auto-migrated).
DATA_FILE = CACHE / "data.json"
_SEC_STORE: dict | None = None
_SEC_LOCK = threading.Lock()


def _secret_seal(raw: bytes) -> dict:
    """Encrypt bytes with the strongest backend that fits their size."""
    if os.name == "nt" and _tpm_selftest():
        if len(raw) <= 180:                       # small (e.g. SGDB key): direct TPM
            blob = _tpm_wrap(raw)
            if blob is not None:
                return {"enc": "tpm", "data": base64.b64encode(blob).decode("ascii")}
        hyb = _seal_hybrid(raw)                    # large (e.g. GOG tokens): TPM+AES
        if hyb is not None:
            return hyb
    if os.name == "nt":
        enc = _dpapi_protect(raw)
        if enc is not None:
            return {"enc": "dpapi", "data": base64.b64encode(enc).decode("ascii")}
    return {"enc": "xor",
            "data": base64.b64encode(bytes(b ^ 0x5A for b in raw)).decode("ascii")}


# TPM-wrapped AES-256-GCM: AES-GCM encrypts data of ANY size (audited crypto from
# the `cryptography` package), the TPM wraps the one-time 32-byte AES key (fits
# RSA-OAEP). Gives full hardware binding to GOG tokens and other large secrets.
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM as _AESGCM
except Exception:
    _AESGCM = None


def _seal_hybrid(raw: bytes) -> dict | None:
    if _AESGCM is None:
        return None
    try:
        key = os.urandom(32)
        wrapped = _tpm_wrap(key)
        if wrapped is None:
            return None
        nonce = os.urandom(12)
        ct = _AESGCM(key).encrypt(nonce, raw, None)
        return {"enc":   "tpm+aes",
                "key":   base64.b64encode(wrapped).decode("ascii"),
                "nonce": base64.b64encode(nonce).decode("ascii"),
                "data":  base64.b64encode(ct).decode("ascii")}
    except Exception as exc:
        log(f"hybrid seal failed: {exc}")
        return None


def _open_hybrid(blob: dict) -> bytes | None:
    if _AESGCM is None:
        return None
    try:
        key = _tpm_unwrap(base64.b64decode(blob["key"]))
        if key is None:                            # foreign machine → re-enter
            return None
        return _AESGCM(key).decrypt(base64.b64decode(blob["nonce"]),
                                    base64.b64decode(blob["data"]), None)
    except Exception as exc:
        log(f"hybrid open failed: {exc}")
        return None


def _secret_open(blob: dict) -> bytes | None:
    if not blob:
        return None
    enc = blob.get("enc")
    if enc == "tpm+aes":
        return _open_hybrid(blob)
    if "data" not in blob:
        return None
    data = base64.b64decode(blob["data"])
    if enc == "tpm":
        return _tpm_unwrap(data)          # None on a foreign machine → re-enter
    if enc == "dpapi":
        return _dpapi_unprotect(data)
    if enc == "xor":
        return bytes(b ^ 0x5A for b in data)
    return None


def _sec_load() -> dict:
    global _SEC_STORE
    if _SEC_STORE is not None:
        return _SEC_STORE
    with _SEC_LOCK:
        if _SEC_STORE is not None:
            return _SEC_STORE
        store = {}
        if DATA_FILE.exists():
            try:
                store = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            except Exception as exc:
                log(f"data.json read failed: {exc}")
                store = {}
        else:
            store = _migrate_secret_files()
            if store:
                _sec_write(store)
        _SEC_STORE = store
        _reseal_if_better()
        return _SEC_STORE


def _reseal_if_better() -> None:
    """If TPM is now available but a stored secret is still under a weaker backend
    (e.g. DPAPI tokens from before TPM support), transparently re-seal it under
    TPM on this machine. Only touches secrets we can currently decrypt."""
    if os.name != "nt" or not _tpm_selftest():
        return
    store = _SEC_STORE or {}
    changed = False
    for ns, blob in list(store.items()):
        enc = (blob or {}).get("enc")
        if enc in ("tpm", "tpm+aes"):
            continue
        raw = _secret_open(blob)
        if not raw:
            continue                     # unreadable here → leave as-is
        store[ns] = _secret_seal(raw)
        if store[ns].get("enc") in ("tpm", "tpm+aes"):
            changed = True
    if changed:
        _sec_write(store)
        log("re-sealed secrets under TPM")


def _sec_write(store: dict | None = None) -> None:
    global _SEC_STORE
    if store is None:
        store = _SEC_STORE or {}
    try:
        CACHE.mkdir(parents=True, exist_ok=True)
        DATA_FILE.write_text(json.dumps(store), encoding="utf-8")
        try: os.chmod(DATA_FILE, 0o600)
        except Exception: pass
    except Exception as exc:
        log(f"data.json write failed: {exc}")
    _SEC_STORE = store


def _sec_get_ns(ns: str) -> dict:
    raw = _secret_open(_sec_load().get(ns))
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return {}


def _sec_set_ns(ns: str, data: dict) -> None:
    store = _sec_load()
    with _SEC_LOCK:
        if data:
            store[ns] = _secret_seal(json.dumps(data).encode("utf-8"))
        else:
            store.pop(ns, None)
        _sec_write(store)


def _migrate_secret_files() -> dict:
    """One-time import of the legacy secrets.json (sgdb) + gog_tokens.json (tokens)
    into the unified store, re-sealing each with its optimal backend."""
    store = {}

    def _open_legacy(path):
        if not path.exists():
            return {}
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            try: return json.loads(path.read_bytes().decode("utf-8"))
            except Exception: return {}
        if isinstance(obj, dict) and obj.get("enc"):
            raw = _secret_open(obj)
            try: return json.loads(raw.decode("utf-8")) if raw else {}
            except Exception: return {}
        return obj if isinstance(obj, dict) else {}

    sgdb = _open_legacy(SECRETS_FILE)
    if sgdb:
        store["sgdb"] = _secret_seal(json.dumps(sgdb).encode("utf-8"))
    tokens = _open_legacy(GOG_TOKENS_FILE)
    if tokens:
        store["tokens"] = _secret_seal(json.dumps(tokens).encode("utf-8"))
    if store:
        log("migrated legacy secret files into data.json")
    return store


def security_status() -> dict:
    """Report which at-rest backend protects the secrets, for the UI."""
    store = _sec_load()
    used = (store.get("sgdb") or store.get("tokens") or {}).get("enc")
    if used in ("tpm", "tpm+aes"):
        backend = "tpm"
    elif used:
        backend = used
    else:
        backend = ("tpm" if _tpm_selftest() else "dpapi") if os.name == "nt" else "xor"
    return {"ok": True, "backend": backend, "tpm": backend == "tpm"}


def _get_secret(name: str) -> str:
    return str(_sec_get_ns("sgdb").get(name) or "")


def _set_secret(name: str, value: str) -> None:
    s = _sec_get_ns("sgdb")
    if value:
        s[name] = value
    else:
        s.pop(name, None)
    _sec_set_ns("sgdb", s)


# ── status scanning ────────────────────────────────────────────────────────────

def _installer_candidates(g: dict) -> list:
    """Candidate subdirectory names that lgogdownloader might create under BASE.
    lgogdownloader typically uses the game title (possibly sanitised), the slug,
    or the game_key.  We try common variants to maximise detection accuracy."""
    slug     = (g.get("slug")     or "").strip()
    game_key = (g.get("game_key") or "").strip()
    title    = (g.get("title")    or "").strip()
    seen, out = set(), []
    for name in [
        slug,
        game_key,
        title,
        title.replace(" ", "_"),
        re.sub(r"[^\w\s\-]", "", title).strip(),
        re.sub(r"\s+", "_", re.sub(r"[^\w\s]", "", title).strip()).lower(),
        re.sub(r"\s+", "_", re.sub(r"[^\w\s]", "", title).strip()),
    ]:
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def scan_downloaded_games() -> dict:
    """Scan BASE for downloaded game folders. A folder counts as 'downloaded'
    if it holds installer files (INSTALLER_EXTS in its root) AND/OR bonus content
    (any files under an extras/ subfolder, or non-installer files in the root when
    extras aren't separated). Returns {dirname_lower: {...}}."""
    result = {}
    if not BASE.exists():
        return result
    try:
        for d in BASE.iterdir():
            if not d.is_dir() or d.name.startswith("_"):
                continue
            inst_files = []
            for pat in INSTALLER_EXTS:
                inst_files.extend(d.glob(pat))
            inst_names = {f.name for f in inst_files}
            inst_size  = sum(f.stat().st_size for f in inst_files if f.is_file())

            # Extras: everything under extras/ (any extension), plus root files
            # that aren't installers (covers the extras_subdir = False layout).
            extra_files = []
            extras_dir  = d / "extras"
            if extras_dir.is_dir():
                extra_files.extend(f for f in extras_dir.rglob("*") if f.is_file())
            for f in d.iterdir():
                if f.is_file() and f.name not in inst_names:
                    extra_files.append(f)
            extra_size = sum(f.stat().st_size for f in extra_files)

            if inst_files or extra_files:
                result[d.name.lower()] = {
                    "path":          str(d),
                    "files":         [f.name for f in sorted(inst_files)],
                    "size":          inst_size,
                    "extras_files":  sorted(f.name for f in extra_files),
                    "extras_size":   extra_size,
                    "has_installer": bool(inst_files),
                }
    except Exception as exc:
        log(f"scan_downloaded_games error: {exc}")
    return result


def scan_installed_games() -> dict:
    """Scan GOG_GAMES for goggame-{id}.info files.
    GOG Galaxy places one in the root of every installed game's directory.
    Returns {game_id_str: install_path_str}."""
    result = {}
    if not GOG_GAMES.exists():
        return result
    try:
        for game_dir in GOG_GAMES.iterdir():
            if not game_dir.is_dir():
                continue
            # Instalacja z depotu w toku / do wznowienia: plik gry
            # goggame-*.info bywa pobrany z depotu ZANIM reszta się ukończy,
            # a stan wznawiania (_goginstall_state.json) kasujemy dopiero po
            # sukcesie. Dopóki on jest, gra NIE jest jeszcze zainstalowana —
            # inaczej wznowienie widziałoby ją jako „już zainstalowaną".
            if (game_dir / _DEPOT_STATE_NAME).exists():
                continue
            for info in game_dir.glob("goggame-*.info"):
                m = re.match(r"goggame-(\d+)\.info$", info.name)
                if m:
                    result[m.group(1)] = str(game_dir)
    except Exception as exc:
        log(f"scan_installed_games error: {exc}")
    return result


def _check_downloaded_for_game(g: dict, downloaded_map: dict) -> dict:
    for dirname in _installer_candidates(g):
        data = downloaded_map.get(dirname.lower())
        if data:
            return {
                "downloaded":      True,
                "installer_path":  data["path"],
                "installer_files": data["files"],
                "installer_size":  data["size"],
                "extras_files":    data.get("extras_files", []),
                "extras_size":     data.get("extras_size", 0),
                "has_installer":   data.get("has_installer", bool(data["files"])),
            }
    return {
        "downloaded":      False,
        "installer_path":  None,
        "installer_files": [],
        "installer_size":  0,
        "extras_files":    [],
        "extras_size":     0,
        "has_installer":   False,
    }


# ── game scanning ───────────────────────────────────────────────────────────────

def scan_games() -> list:
    games = []
    for slug, entry in _lib_all().items():
        prod = entry.get("product")
        if not prod:
            continue
        det   = entry.get("details") or {}
        key   = entry.get("key") or slug
        slug2 = prod.get("slug") or slug
        title = prod.get("title") or det.get("title") or key.replace("_", " ").title()
        games.append({
            "id":           str(prod.get("id") or slug2),
            "slug":         slug2,
            "game_key":     key,
            "title":        title,
            "root":         f"pak://{slug2}",
            "product_path": f"pak://{slug2}/product",
            "details_path": f"pak://{slug2}/details",
            "icon":         norm_url(prod.get("images", {}).get("icon")),
            "logo":         norm_url(prod.get("images", {}).get("logo")),
            "background":   norm_url(
                prod.get("images", {}).get("background") or det.get("backgroundImage")
            ),
            "release_date": prod.get("release_date"),
            "rating":       (entry.get("rating") or {}).get("value"),
            "rating_count": (entry.get("rating") or {}).get("count"),
            "installable":  bool(prod.get("is_installable", False)),
            "platforms":    [k for k, v in (prod.get("content_system_compatibility") or {}).items() if v],
            "languages":    list((prod.get("languages") or {}).values()),
            "product":      prod,
            "details":      det,
            "sgdb_id":      entry.get("sgdb_id"),
        })
    games.sort(key=lambda x: x["title"].lower())
    log(f"scan_games -> {len(games)}")
    return games


def build_index() -> dict:
    """Refresh the in-memory library counts. The old index.sqlite was never read
    back (get_games reads the packed library directly), so we no longer write it —
    one fewer file in the cache."""
    ensure_dirs()
    games = scan_games()
    log(f"build_index -> {len(games)}")
    return {
        "ok":         True,
        "count":      len(games),
        "json_dir":   str(JSON_DIR),
        "install_dir": str(BASE),
        "games_dir":  str(GOG_GAMES),
    }


def get_games() -> list:
    """Return all games enriched with live downloaded/installed status."""
    installed  = scan_installed_games()   # one directory scan
    downloaded = scan_downloaded_games()  # one directory scan
    pranks     = _load_purchase_ranks()   # {product_id: rank} — „by purchase date"
    result = []
    for g in scan_games():
        dl = _check_downloaded_for_game(g, downloaded)
        result.append({
            "id":           g["id"],
            "slug":         g["slug"],
            "game_key":     g["game_key"],
            "title":        g["title"],
            "icon":         g["icon"],
            "logo":         g["logo"],
            "background":   g["background"],
            "platforms":    g["platforms"],
            "languages":    g["languages"],
            "installable":  g["installable"],
            "release_date": g["release_date"],
            "rating":       g["rating"],
            "rating_count": g["rating_count"],
            "product":      g["product"],
            "details":      g["details"],
            # ── live status ──────────────────────────────────────
            "installed":       g["id"] in installed,
            "installed_path":  installed.get(g["id"]),
            "purchase_rank":   pranks.get(g["id"]),
            "downloaded":      dl["downloaded"],
            "installer_path":  dl["installer_path"],
            "installer_files": dl["installer_files"],
            "installer_size":  dl["installer_size"],
            "extras_files":    dl["extras_files"],
            "extras_size":     dl["extras_size"],
            "has_installer":   dl["has_installer"],
        })
    return result


# ── API operations ──────────────────────────────────────────────────────────────

def _hidden_startupinfo():
    if os.name == "nt":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
        return si
    return None


def _emit_queue() -> None:
    """Push the current queue + running label to the UI."""
    try:
        items = [{"id": it["id"], "label": it["label"]} for it in list(_task_queue)]
    except Exception:
        items = []
    _send_js({"type": "queue", "items": items,
              "running": _current_label if _is_running else ""})


def _js_command_finished(ok: bool) -> None:
    try:
        webview.windows[0].evaluate_js(
            f"window.onCommandFinished?.({json.dumps({'ok': ok, 'rc': 0 if ok else 1})})"
        )
    except Exception as exc:
        log(f"[onCommandFinished error] {exc}")


def _run_thread(target, label: str) -> None:
    """Start `target` on a background thread. When it ends, automatically pull the
    next queued job (if any) and run it too — a sequential pipeline."""
    global _is_running, _current_label
    _current_label = label or ""
    _cancel.clear()
    _send_js({"type": "task_started", "label": _current_label})
    _emit_queue()

    def worker() -> None:
        global _is_running, _current_label
        ok = False
        try:
            ok = bool(target())
        except Exception as exc:
            _push_log(f"✗ Wyjątek: {exc}")
        finally:
            nxt = None
            with _proc_lock:
                if _task_queue:
                    nxt = _task_queue.popleft()
                else:
                    _is_running = False
                    _current_label = ""
            _js_command_finished(ok)
            _emit_queue()
            if nxt is not None:
                _push_log(f"▶ Kolejka: „{nxt['label']}”…")
                _run_thread(nxt["target"], nxt["label"])

    threading.Thread(target=worker, daemon=True).start()


def _submit_task(target, label: str, queueable: bool = False) -> dict:
    """Run `target` now if idle, otherwise reject — or, when `queueable`, append it
    to the sequential queue and report its position."""
    global _is_running, _task_seq
    with _proc_lock:
        if _is_running:
            if queueable:
                _task_seq += 1
                item = {"id": _task_seq, "label": label, "target": target}
                _task_queue.append(item)
                pos = len(_task_queue)
                _emit_queue()
                return {"ok": True, "queued": True, "position": pos, "id": _task_seq}
            return {"ok": False, "error": "Inne polecenie jest już uruchomione."}
        _is_running = True
    _run_thread(target, label)
    return {"ok": True, "started": True}


def _run_python_task(target, label: str) -> dict:
    """Non-queueable task (sync, update, …): runs now or is rejected if busy."""
    return _submit_task(target, label, queueable=False)


def get_queue() -> dict:
    return {"ok": True,
            "running": _current_label if _is_running else "",
            "items": [{"id": it["id"], "label": it["label"]} for it in list(_task_queue)]}


def cancel_queued(item_id) -> dict:
    """Remove a *pending* queued job (not the one currently running)."""
    try:
        iid = int(item_id)
    except Exception:
        return {"ok": False, "error": "zła pozycja"}
    with _proc_lock:
        before = len(_task_queue)
        remaining = [it for it in _task_queue if it["id"] != iid]
        _task_queue.clear()
        _task_queue.extend(remaining)
        removed = before - len(_task_queue)
    _emit_queue()
    return {"ok": True, "removed": removed}


def clear_queue() -> dict:
    with _proc_lock:
        n = len(_task_queue)
        _task_queue.clear()
    _emit_queue()
    return {"ok": True, "removed": n}


def _legacy_tokens() -> dict | None:
    """Read lgogdownloader's galaxy_tokens.json for one-time migration.
    Linux: read the file directly. Windows: read it out of WSL."""
    try:
        if os.name != "nt":
            p = Path.home() / ".config" / "lgogdownloader" / "galaxy_tokens.json"
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8"))
            return None
        out = subprocess.run(GALAXY_TOKENS_CAT, capture_output=True, startupinfo=_hidden_startupinfo())
        if out.returncode == 0 and out.stdout.strip():
            return json.loads(out.stdout.decode("utf-8", "replace"))
    except Exception as exc:
        log(f"legacy token read failed: {exc}")
    return None


# ── encrypted token store ──────────────────────────────────────────────────────
# Tokens must stay *readable* by the app (they are sent to GOG on every call),
# so one-way hashing is impossible — encryption at rest is the correct tool.
# Windows: DPAPI (CryptProtectData), bound to the current user account.
# Linux:   file stored with 0600 permissions (owner-only).
# The GOG password itself is NEVER stored — login happens in the browser.

def _dpapi_protect(data: bytes) -> bytes | None:
    try:
        import ctypes, ctypes.wintypes as wt

        class BLOB(ctypes.Structure):
            _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        blob_in  = BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data, len(data)),
                                               ctypes.POINTER(ctypes.c_char)))
        blob_out = BLOB()
        if not ctypes.windll.crypt32.CryptProtectData(
                ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
            return None
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)
    except Exception as exc:
        log(f"dpapi protect failed: {exc}")
        return None


def _dpapi_unprotect(data: bytes) -> bytes | None:
    try:
        import ctypes, ctypes.wintypes as wt

        class BLOB(ctypes.Structure):
            _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        blob_in  = BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data, len(data)),
                                               ctypes.POINTER(ctypes.c_char)))
        blob_out = BLOB()
        if not ctypes.windll.crypt32.CryptUnprotectData(
                ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
            return None
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)
    except Exception as exc:
        log(f"dpapi unprotect failed: {exc}")
        return None




def _write_galaxy_tokens(tokens: dict) -> None:
    """Persist GOG tokens into the unified secrets store (DPAPI-sealed on Windows)."""
    _sec_set_ns("tokens", tokens)


def _read_galaxy_tokens() -> dict:
    """Load tokens from the unified store; on first run migrate lgogdownloader's
    plaintext file. On a foreign machine the seal won't open → prompt re-login."""
    tokens = _sec_get_ns("tokens")
    if tokens and "access_token" in tokens:
        return tokens
    # data.json exists but tokens namespace is present yet unreadable here
    # (different machine / reset TPM) → treat as "must log in again".
    if "tokens" in _sec_load():
        raise RuntimeError("Nie można odczytać logowania GOG na tym komputerze. "
                           "Zaloguj się ponownie.")
    legacy = _legacy_tokens()
    if legacy:
        _write_galaxy_tokens(legacy)         # migrate into the encrypted store
        return legacy
    raise RuntimeError("Brak zapisanego logowania GOG. Kliknij „Zaloguj do GOG”.")


# ── GOG login (browser OAuth, no lgogdownloader) ───────────────────────────────

def _exchange_code(code: str) -> dict:
    params = urllib.parse.urlencode({
        "client_id":     GOG_CLIENT_ID,
        "client_secret": GOG_CLIENT_SECRET,
        "grant_type":    "authorization_code",
        "code":          code,
        "redirect_uri":  GOG_REDIRECT,
    })
    req = urllib.request.Request(f"{GOG_AUTH_TOKEN_URL}?{params}",
                                 headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _login_url() -> str:
    return (f"{GOG_AUTH_PAGE}?client_id={GOG_CLIENT_ID}"
            f"&redirect_uri={urllib.parse.quote(GOG_REDIRECT, safe='')}"
            f"&response_type=code&layout=client2")


def _extract_code(pasted: str) -> str | None:
    pasted = (pasted or "").strip()
    if not pasted:
        return None
    # full redirect URL → pull ?code=… ; otherwise treat the text as the code itself
    if "code=" in pasted:
        q = urllib.parse.urlparse(pasted).query or pasted.split("?", 1)[-1]
        val = urllib.parse.parse_qs(q).get("code", [None])[0]
        if val:
            return val
    if re.fullmatch(r"[A-Za-z0-9_\-]+", pasted):
        return pasted
    return None


def gog_login_start() -> dict:
    """Open GOG's login page in the system browser and return the URL too.
    After signing in, the browser lands on a blank on_login_success page whose
    address bar holds ?code=… — the user pastes that URL/code into the app."""
    url = _login_url()
    try:
        webbrowser.open(url)
    except Exception:
        pass
    return {"ok": True, "url": url}


def gog_login_finish(pasted: str) -> dict:
    code = _extract_code(pasted)
    if not code:
        return {"ok": False, "error": "Nie znaleziono kodu. Wklej cały adres on_login_success lub sam kod."}
    try:
        toks = _exchange_code(code)
    except Exception as exc:
        return {"ok": False, "error": f"Wymiana kodu nie powiodła się: {exc}"}
    if not toks.get("access_token"):
        return {"ok": False, "error": "GOG nie zwrócił access_token."}
    _write_galaxy_tokens(toks)
    return {"ok": True}


def get_onboarding_state() -> dict:
    """Report what the first-run wizard needs: whether directories were ever
    configured, whether GOG is logged in, and how many games are indexed.
    The frontend uses `configured` to decide whether to auto-skip the wizard."""
    st = get_settings()
    dirs_set = bool(st.get("json_dir") or st.get("install_dir") or st.get("games_dir"))
    try:
        logged = bool(gog_login_status().get("logged_in"))
    except Exception:
        logged = False
    try:
        n_games = len(scan_games())
    except Exception:
        n_games = 0
    return {
        "ok": True,
        "settings_exists": SETTINGS_FILE.exists(),
        "dirs_configured": dirs_set,
        "logged_in": logged,
        "games_indexed": n_games,
        # Skip the wizard automatically once the user has a working setup.
        "configured": bool(dirs_set or n_games or st.get("onboarded")),
        "lang": st.get("lang", "pl"),
    }


def mark_onboarded() -> dict:
    save_settings({"onboarded": True})
    return {"ok": True}


def gog_login_status() -> dict:
    """Quick check: do we have a usable token (owned-games call succeeds)?"""
    try:
        tokens = _read_galaxy_tokens()
    except Exception:
        return {"ok": True, "logged_in": False}
    box = {"tokens": tokens, "access": tokens.get("access_token"),
           "refresh": tokens.get("refresh_token")}
    try:
        _gog_get_json(GOG_OWNED_API, box["access"])
        return {"ok": True, "logged_in": True}
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403) and box["refresh"]:
            try:
                new = _refresh_access_token(box["refresh"])
                for k in ("access_token", "refresh_token", "expires_in", "expires_at",
                          "session_id", "token_type", "scope", "user_id"):
                    if k in new:
                        tokens[k] = new[k]
                _write_galaxy_tokens(tokens)
                return {"ok": True, "logged_in": True}
            except Exception:
                return {"ok": True, "logged_in": False}
        return {"ok": True, "logged_in": False}
    except Exception:
        return {"ok": True, "logged_in": False}


def _refresh_access_token(refresh_token: str) -> dict:
    params = urllib.parse.urlencode({
        "client_id":     GOG_CLIENT_ID,
        "client_secret": GOG_CLIENT_SECRET,
        "grant_type":    "refresh_token",
        "refresh_token": refresh_token,
    })
    req = urllib.request.Request(f"{GOG_AUTH_TOKEN_URL}?{params}",
                                 headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _gog_get_json(url: str, access_token: str) -> dict:
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {access_token}",
        "User-Agent":    "Mozilla/5.0",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _get_owned_product_ids() -> list:
    """Fresh list of owned product IDs from the GOG account API.
    Refreshes the access token (and writes it back) if it has expired."""
    tokens  = _read_galaxy_tokens()
    access  = tokens.get("access_token")
    refresh = tokens.get("refresh_token")
    if not access:
        raise RuntimeError("brak access_token w galaxy_tokens.json")
    try:
        data = _gog_get_json(GOG_OWNED_API, access)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403) and refresh:
            _push_log("Token wygasł — odświeżam…")
            new = _refresh_access_token(refresh)
            access = new.get("access_token")
            if not access:
                raise RuntimeError("odświeżenie tokenu nie zwróciło access_token")
            for k in ("access_token", "refresh_token", "expires_in", "expires_at",
                      "session_id", "token_type", "scope", "user_id"):
                if k in new:
                    tokens[k] = new[k]
            _write_galaxy_tokens(tokens)
            data = _gog_get_json(GOG_OWNED_API, access)
        else:
            raise
    return [str(i) for i in (data.get("owned") or [])]


# ── Kolejność zakupów („by purchase date" jak na stronie GOG) ───────────────────
GOG_FILTERED_API = "https://embed.gog.com/account/getFilteredProducts"
PURCHASE_FILE    = CACHE / "purchase_order.json"


def _gog_get_json_auth(url: str) -> dict:
    """Authed GET z jednym automatycznym odświeżeniem tokenu na 401/403."""
    tokens  = _read_galaxy_tokens()
    access  = tokens.get("access_token")
    refresh = tokens.get("refresh_token")
    if not access:
        raise RuntimeError("brak access_token w galaxy_tokens.json")
    try:
        return _gog_get_json(url, access)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403) and refresh:
            new = _refresh_access_token(refresh)
            access = new.get("access_token")
            if not access:
                raise RuntimeError("odświeżenie tokenu nie zwróciło access_token")
            for k in ("access_token", "refresh_token", "expires_in", "expires_at",
                      "session_id", "token_type", "scope", "user_id"):
                if k in new:
                    tokens[k] = new[k]
            _write_galaxy_tokens(tokens)
            return _gog_get_json(url, access)
        raise


def _fetch_purchase_ranks() -> dict:
    """Kolejność zakupów jak „by purchase date" na stronie GOG: przechodzi
    getFilteredProducts?sortBy=date_purchased (od najświeższego zakupu) i nadaje
    każdemu product_id rangę (0 = kupione najświeżej). {product_id: rank}."""
    ranks: dict = {}
    rank, page, pages = 0, 1, 1
    while page <= pages and page <= 200:          # twardy limit stron (bezpiecznik)
        data  = _gog_get_json_auth(f"{GOG_FILTERED_API}?mediaType=1"
                                   f"&sortBy=date_purchased&page={page}")
        pages = int(data.get("totalPages") or 1)
        for p in (data.get("products") or []):
            pid = str(p.get("id") or "").strip()
            if pid and pid not in ranks:
                ranks[pid] = rank
                rank += 1
        page += 1
    return ranks


def _load_purchase_ranks() -> dict:
    try:
        return json.loads(PURCHASE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _refresh_purchase_worker() -> bool:
    _push_log("Pobieram kolejność zakupów z GOG…")
    try:
        ranks = _fetch_purchase_ranks()
    except Exception as exc:
        _push_log(f"✗ Nie udało się pobrać dat zakupu: {exc}")
        return False
    if not ranks:
        _push_log("⚠ GOG nie zwrócił kolejności zakupów (pusta lista).")
        return False
    try:
        PURCHASE_FILE.write_text(json.dumps(ranks), encoding="utf-8")
    except Exception as exc:
        _push_log(f"✗ Zapis dat zakupu: {exc}")
        return False
    _push_log(f"✓ Kolejność zakupów zapisana: {len(ranks)} gier.")
    return True


def refresh_purchase_dates() -> dict:
    return _run_python_task(lambda: _refresh_purchase_worker(), "PURCHASE")


def _fetch_product(product_id: str) -> dict | None:
    """Fetch the full product JSON from the public GOG products API.
    Returns None on 404 (delisted titles / goodie packs) or any error."""
    url = GOG_PRODUCT_API.format(id=product_id)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as exc:
        log(f"product fetch {product_id} :: {exc}")
        return None


def _fetch_gog_rating(product_id: str) -> dict | None:
    """GOG's own verified-owner average rating for a product (0–5), e.g.
    {"value": 4.4, "count": 3306}. Metacritic is not exposed by GOG's API, so
    this is the available, first-party rating. Returns None on any error."""
    url = f"https://reviews.gog.com/v1/products/{product_id}/averageRating?reviewer=verified_owner"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        val = data.get("value")
        return {"value": round(float(val), 1), "count": int(data.get("count") or 0)} \
            if val is not None else None
    except Exception as exc:
        log(f"rating fetch {product_id} :: {exc}")
        return None


def _write_product_json(slug: str, product: dict) -> None:
    """Store a product's JSON in the packed library (keyed by slug)."""
    _lib_put(product.get("slug") or slug, product)


def _sync_all_worker() -> bool:
    _push_log("Pobieram listę posiadanych gier z konta GOG…")
    try:
        ids = _get_owned_product_ids()
    except Exception as exc:
        _push_log(f"✗ {exc}")
        return False

    total = len(ids)
    if not total:
        _push_log("✗ Lista posiadanych gier jest pusta.")
        return False
    _push_log(f"Posiadanych produktów: {total}. Pobieram metadane z api.gog.com "
              "(tylko gry; DLC i dodatki pomijam)…")

    state = {"done": 0, "games": 0, "skipped": 0, "missing": 0}
    lock  = threading.Lock()
    collected = []

    def handle(pid: str) -> None:
        prod = _fetch_product(pid)
        rating = _fetch_gog_rating(pid) if prod and prod.get("game_type") == "game" else None
        with lock:
            state["done"] += 1
            if prod is None:
                state["missing"] += 1                      # 404: goodie pack / delisted
            elif prod.get("game_type") == "game":
                slug = (prod.get("slug") or f"product_{pid}").strip()
                collected.append((slug, prod, rating))
                state["games"] += 1
                _send_js({"type": "completion", "filename": slug, "speed": "JSON"})
            else:
                state["skipped"] += 1                        # dlc / pack
            if state["done"] % 50 == 0 or state["done"] == total:
                _push_log(f"… {state['done']}/{total} (gry: {state['games']})")

    with ThreadPoolExecutor(max_workers=_GOG_FETCH_WORKERS) as ex:
        list(ex.map(handle, ids))

    # Single packed write for the whole batch (fast, atomic).
    if collected:
        _lib_put_many(collected)

    _push_log(f"✓ Gotowe: {state['games']} gier zapisanych, "
              f"{state['skipped']} DLC/dodatków pominięto, "
              f"{state['missing']} niedostępnych w API.")
    return True


def _sync_one_worker(game_id) -> bool:
    g = next((x for x in scan_games() if x["id"] == str(game_id)), None)
    if not g:
        _push_log("✗ Gra nie znaleziona.")
        return False
    pid  = str(g["product"].get("id") or "").strip()
    slug = g["slug"] or g["game_key"]
    if not pid:
        _push_log("✗ Brak product_id dla tej gry.")
        return False
    _push_log(f"Pobieram metadane: {slug}…")
    prod = _fetch_product(pid)
    if not prod:
        _push_log("✗ Nie udało się pobrać danych z api.gog.com.")
        return False
    rating = _fetch_gog_rating(pid)
    _lib_put_many([(prod.get("slug") or slug, prod, rating)])
    _send_js({"type": "completion", "filename": slug, "speed": "JSON"})
    _push_log("✓ Zapisano.")
    return True


def _refresh_ratings_worker(only_missing: bool = True) -> bool:
    """Fetch GOG's own user rating for library games (no product re-fetch), so
    ratings can be populated quickly without a full sync."""
    lib = _lib_all()
    targets = []
    for slug, entry in lib.items():
        prod = entry.get("product") or {}
        pid  = str(prod.get("id") or "").strip()
        if not pid:
            continue
        if only_missing and (entry.get("rating") or {}).get("value") is not None:
            continue
        targets.append((slug, pid))

    if not targets:
        _push_log("Wszystkie gry mają już ocenę GOG.")
        return True

    _push_log(f"Pobieram oceny GOG dla {len(targets)} gier…")
    results = {}
    state   = {"done": 0}
    lock    = threading.Lock()

    def handle(item):
        slug, pid = item
        if _cancel.is_set():
            return
        r = _fetch_gog_rating(pid)
        with lock:
            state["done"] += 1
            if r:
                results[slug] = r
            if state["done"] % 50 == 0 or state["done"] == len(targets):
                _push_log(f"… {state['done']}/{len(targets)}")

    with ThreadPoolExecutor(max_workers=_GOG_FETCH_WORKERS) as ex:
        list(ex.map(handle, targets))

    lib = _lib_load()
    with _LIB_LOCK:
        for slug, r in results.items():
            if slug in lib:
                lib[slug]["rating"] = r
        _lib_save(lib)
    _push_log(f"✓ Oceny GOG zapisane: {len(results)}/{len(targets)}.")
    return True


def refresh_ratings() -> dict:
    return _run_python_task(lambda: _refresh_ratings_worker(True), "RATINGS")


def sync_json_all() -> dict:
    return _run_python_task(_sync_all_worker, "SYNC_ALL")


def sync_json_game(game_id) -> dict:
    return _run_python_task(lambda: _sync_one_worker(game_id), "SYNC_GAME")


# ── selective download (pure-Python, GOG API only) ─────────────────────────────

# This machine runs Windows, so the user's platform is "windows".
_MY_OS = "windows"

# Names that signal an *old game version* parked in extras (to default-uncheck).
_HEAVY_RE = re.compile(
    r"(part\s*\d+|language\s+patch|\bclassic\b|\(dos version|\(floppy version|"
    r"original\b.*\bgame\b|\b1998\b|hotfix|re-?installer|\brom\b|\(definitive edition)",
    re.I,
)
# Trailing "Part N" used to collapse multi-part packs into one row.
_PART_TAIL_RE = re.compile(r"\s*part\s*\d+\s*$", re.I)
# GOG build id baked into offline-installer filenames, e.g. "…_(82340).exe".
# A different build ⇒ a different tag, so name+size is enough to trust such files.
_BUILD_TAG_RE = re.compile(r"\(\d{4,}\)")


def _parts_of(entry: dict) -> list:
    out = []
    for f in entry.get("files") or []:
        if f.get("downlink"):
            out.append({"file_id": f.get("id"), "size": f.get("size") or 0,
                        "downlink": f.get("downlink")})
    return out


def _simple_rows(items, category, verify) -> list:
    rows = []
    for it in items or []:
        parts = _parts_of(it)
        if not parts:
            continue
        rows.append({
            "key":       f"{category}:{it.get('id')}",
            "category":  category,
            "os":        (it.get("os") or "").lower(),
            "lang":      (it.get("language") or "").lower(),
            "lang_full": it.get("language_full") or "",
            "version":   it.get("version") or "",
            "name":      it.get("name") or "",
            "size":      it.get("total_size") or sum(p["size"] for p in parts),
            "parts":     parts,
            "default":   False,
            "verify":    verify,
        })
    return rows


def _group_extras(raw: list) -> list:
    groups, singles = {}, []
    for ex in raw:
        if _PART_TAIL_RE.search(ex["name"]):
            base = _PART_TAIL_RE.sub("", ex["name"]).strip() or ex["name"]
            groups.setdefault(base, []).append(ex)
        else:
            singles.append(ex)

    out = []
    for base, items in groups.items():
        if len(items) == 1:
            singles.append(items[0])
            continue
        all_parts = [p for i in items for p in i["parts"]]
        out.append({
            "key":      f"extra-group:{base}",
            "category": "extra",
            "group":    True,
            "name":     f"{base} ({len(items)} plików)",
            "type":     items[0]["type"],
            "size":     sum(i["size"] for i in items),
            "parts":    all_parts,
            "heavy":    True,           # multi-part pack ⇒ treat as heavy old version
            "default":  False,
            "verify":   False,
        })
    for ex in singles:
        out.append({
            "key":      f"extra:{ex['id']}",
            "category": "extra",
            "group":    False,
            "name":     ex["name"],
            "type":     ex["type"],
            "size":     ex["size"],
            "parts":    ex["parts"],
            "heavy":    ex["heavy"],
            "default":  (not ex["heavy"]),   # ordinary extras on, heavy ones off
            "verify":   False,
        })
    out.sort(key=lambda e: (e["type"], not e.get("group", False), e["name"].lower()))
    return out


def _build_manifest(product: dict, owned_ids: set | None = None) -> dict:
    dl = product.get("downloads") or {}

    installers = []
    for ins in dl.get("installers") or []:
        parts = _parts_of(ins)
        if not parts:
            continue
        os_  = (ins.get("os") or "").lower()
        lang = (ins.get("language") or "").lower()
        installers.append({
            "key":       f"installer:{ins.get('id')}",
            "category":  "installer",
            "os":        os_,
            "lang":      lang,
            "lang_full": ins.get("language_full") or lang,
            "version":   ins.get("version") or "",
            "name":      ins.get("name") or "",
            "size":      ins.get("total_size") or sum(p["size"] for p in parts),
            "parts":     parts,
            "default":   (os_ == _MY_OS and lang == "en"),
            "verify":    True,
        })

    patches    = _simple_rows(dl.get("patches"),        "patch",         True)
    langpacks  = _simple_rows(dl.get("language_packs"), "language_pack", True)

    raw_extras = []
    for ex in dl.get("bonus_content") or []:
        parts = _parts_of(ex)
        if not parts:
            continue
        name  = ex.get("name") or ""
        etype = ex.get("type") or ""
        size  = ex.get("total_size") or sum(p["size"] for p in parts)
        heavy = bool(_HEAVY_RE.search(name)) or (etype == "game add-ons" and size > 1_000_000_000)
        raw_extras.append({"id": ex.get("id"), "name": name, "type": etype,
                           "size": size, "parts": parts, "heavy": heavy})
    extras = _group_extras(raw_extras)

    # ── DLC — separate GOG products; their installers live in expanded_dlcs ──
    dlcs = []
    for dlc in product.get("expanded_dlcs") or []:
        dlc_id    = str(dlc.get("id") or "")
        dlc_title = dlc.get("title") or f"DLC {dlc_id}"
        owned     = (owned_ids is None) or (dlc_id in owned_ids)
        ddl       = dlc.get("downloads") or {}
        for ins in ddl.get("installers") or []:
            parts = _parts_of(ins)
            if not parts:
                continue
            os_  = (ins.get("os") or "").lower()
            lang = (ins.get("language") or "").lower()
            dlcs.append({
                "key":       f"dlc:{dlc_id}:installer:{ins.get('id')}",
                "category":  "dlc",
                "os":        os_,
                "lang":      lang,
                "lang_full": ins.get("language_full") or lang,
                "version":   ins.get("version") or "",
                "name":      f"{dlc_title} — {ins.get('name') or 'installer'}",
                "size":      ins.get("total_size") or sum(p["size"] for p in parts),
                "parts":     parts,
                "owned":     owned,
                "default":   owned and os_ == _MY_OS and lang == "en",
                "verify":    True,
            })
        for pat in ddl.get("patches") or []:
            parts = _parts_of(pat)
            if not parts:
                continue
            dlcs.append({
                "key":       f"dlc:{dlc_id}:patch:{pat.get('id')}",
                "category":  "dlc",
                "os":        (pat.get("os") or "").lower(),
                "lang":      (pat.get("language") or "").lower(),
                "lang_full": pat.get("language_full") or "",
                "version":   pat.get("version") or "",
                "name":      f"{dlc_title} — {pat.get('name') or 'patch'}",
                "size":      pat.get("total_size") or sum(p["size"] for p in parts),
                "parts":     parts,
                "owned":     owned,
                "default":   False,
                "verify":    True,
            })

    return {
        "installers":     installers,
        "patches":        patches,
        "language_packs": langpacks,
        "dlcs":           dlcs,
        "extras":         extras,
    }


def get_game_extras(game_id) -> dict:
    """Lightweight list of bonus content (extras) for a game, read straight from
    the local product JSON — no network. Used to show what's available for the
    selected game in the detail view."""
    g = next((x for x in scan_games() if x["id"] == str(game_id)), None)
    if not g:
        return {"ok": False, "error": "Gra nie znaleziona"}
    dl = (g.get("product") or {}).get("downloads") or {}
    raw = []
    for ex in dl.get("bonus_content") or []:
        parts = _parts_of(ex)
        if not parts:
            continue
        name  = ex.get("name") or ""
        etype = ex.get("type") or ""
        size  = ex.get("total_size") or sum(p["size"] for p in parts)
        heavy = bool(_HEAVY_RE.search(name)) or (etype == "game add-ons" and size > 1_000_000_000)
        raw.append({"id": ex.get("id"), "name": name, "type": etype,
                    "size": size, "parts": parts, "heavy": heavy})
    extras = [{"name": e["name"], "type": e["type"], "size": e["size"]}
              for e in _group_extras(raw)]
    return {"ok": True, "extras": extras}


def get_download_manifest(game_id) -> dict:
    g = next((x for x in scan_games() if x["id"] == str(game_id)), None)
    if not g:
        return {"ok": False, "error": "Gra nie znaleziona"}
    prod = g["product"]
    if not (prod.get("downloads") or {}).get("installers"):
        fresh = _fetch_product(str(prod.get("id") or ""))
        if fresh:
            prod = fresh
    # DLC listed under a game include ones you don't own — mark ownership using
    # the account's owned list (best-effort; on failure show all as unknown/owned).
    owned_ids = None
    if prod.get("expanded_dlcs"):
        try:
            owned_ids = set(_get_owned_product_ids())
        except Exception as exc:
            log(f"owned list unavailable for DLC marking: {exc}")
    man = _build_manifest(prod, owned_ids)
    man.update({"ok": True, "game_id": g["id"], "title": g["title"], "slug": g["slug"]})
    return man


# ── downloader internals ───────────────────────────────────────────────────────

def _access_token_box() -> dict:
    tokens  = _read_galaxy_tokens()
    return {"tokens": tokens,
            "access":  tokens.get("access_token"),
            "refresh": tokens.get("refresh_token"),
            "lock":    threading.Lock()}


def _resolve_downlink(downlink_url: str, box: dict) -> dict:
    """api.gog.com downlink endpoint → {downlink: <cdn url>, checksum: <xml url>}.
    Refreshes the access token once on 401/403 (thread-safe for parallel files)."""
    try:
        return _gog_get_json(downlink_url, box["access"])
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403) and box.get("refresh"):
            with box["lock"]:
                # Another worker may have refreshed already — retry with current token.
                try:
                    return _gog_get_json(downlink_url, box["access"])
                except urllib.error.HTTPError as exc2:
                    if exc2.code not in (401, 403):
                        raise
                _push_log("Token wygasł — odświeżam…")
                new = _refresh_access_token(box["refresh"])
                box["access"] = new.get("access_token")
                for k in ("access_token", "refresh_token", "expires_in", "expires_at",
                          "session_id", "token_type", "scope", "user_id"):
                    if k in new:
                        box["tokens"][k] = new[k]
                _write_galaxy_tokens(box["tokens"])
            return _gog_get_json(downlink_url, box["access"])
        raise


def _filename_from(resp, cdn_url: str) -> str:
    cd = resp.headers.get("Content-Disposition") or ""
    m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', cd)
    if m:
        return urllib.parse.unquote(m.group(1).strip())
    path = urllib.parse.urlparse(cdn_url).path
    return urllib.parse.unquote(os.path.basename(path)) or "downloaded.bin"


def _filename_from_url(cdn_url: str) -> str:
    path = urllib.parse.urlparse(cdn_url).path
    return urllib.parse.unquote(os.path.basename(path)) or "downloaded.bin"


def _md5_from_checksum_xml(xml_text: str) -> str | None:
    try:
        root = ET.fromstring(xml_text)
        return root.attrib.get("md5")          # GOG puts whole-file md5 on <file md5="…">
    except Exception:
        return None


def _human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024


class _ProgressHub:
    """Aggregates per-file progress slots and emits combined progress + a total."""
    def __init__(self, grand_total: int):
        self.lock  = threading.Lock()
        self.grand = grand_total
        self.done  = 0                 # fully finished bytes
        self.slots = {}                # slot_id -> {filename,size,got,t0}
        self.t0    = time.time()
        self.last  = 0.0

    def start(self, sid, name, size):
        with self.lock:
            self.slots[sid] = {"id": sid, "filename": name, "size": size,
                               "got": 0, "t0": time.time()}
        self._emit(force=True)

    def progress(self, sid, got):
        do_emit = False
        with self.lock:
            s = self.slots.get(sid)
            if s:
                s["got"] = got
            now = time.time()
            if now - self.last > 0.3:
                self.last = now
                do_emit = True
        if do_emit:
            self._emit()

    def finish(self, sid, completed=True):
        with self.lock:
            s = self.slots.pop(sid, None)
            if s and completed:
                self.done += s["size"]
        self._emit(force=True)

    def _emit(self, force=False):
        with self.lock:
            slots, live = [], 0
            for s in self.slots.values():
                el  = max(time.time() - s["t0"], 1e-6)
                spd = s["got"] / el
                live += s["got"]
                tot = s["size"] or 0
                slots.append({
                    "id": s["id"], "filename": s["filename"],
                    "pct": int(s["got"] * 100 / tot) if tot else 0,
                    "transferred": _human(s["got"]).split()[0],
                    "total": _human(tot).split()[0],
                    "unit":  _human(tot).split()[1] if tot else "",
                    "speed": f"{spd/1024/1024:.1f}", "speed_unit": "MB/s",
                    "eta": "—", "finished": False,
                })
            transferred = self.done + live
            elapsed = max(time.time() - self.t0, 1e-6)
            gspeed  = transferred / elapsed
            remaining = max(self.grand - transferred, 0)
            geta = remaining / gspeed if gspeed > 0 else 0
            total = {
                "speed": f"{gspeed/1024/1024:.1f} MB/s",
                "remaining": "",
                "size": f"{_human(transferred)} / {_human(self.grand)}",
                "eta": time.strftime("%H:%M:%S", time.gmtime(geta)) if geta else "",
            }
        _send_js({"type": "progress", "slots": slots, "total": total})


def _open_response(cdn_url: str, byte_range: str | None = None):
    headers = {"User-Agent": "Mozilla/5.0"}
    if byte_range:
        headers["Range"] = byte_range
    return urllib.request.urlopen(
        urllib.request.Request(cdn_url, headers=headers), timeout=60)


def _download_stream(cdn_url: str, dest: Path, sid: int, hub: _ProgressHub) -> None:
    """Single-connection download with simple append-resume."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    existing = dest.stat().st_size if dest.exists() else 0
    try:
        resp = _open_response(cdn_url, f"bytes={existing}-" if existing else None)
    except urllib.error.HTTPError as exc:
        if exc.code == 416 and existing:
            # Existing file is already >= the server's size (complete or stale):
            # a resume range is unsatisfiable, so fetch the whole file fresh.
            resp = _open_response(cdn_url)
            existing = 0
        else:
            raise
    status = getattr(resp, "status", resp.getcode())
    if status == 206:
        mode = "ab"
    else:
        existing, mode = 0, "wb"
    got = existing
    with open(dest, mode) as fh:
        while True:
            if _cancel.is_set():
                raise RuntimeError("anulowano")
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            fh.write(chunk)
            got += len(chunk)
            hub.progress(sid, got)


def _download_segmented(cdn_url: str, dest: Path, size: int, segments: int,
                        sid: int, hub: _ProgressHub) -> None:
    """Multi-connection download writing into one pre-allocated file via seek.
    Resume state lives in a <dest>.gogpart sidecar (list of {start,end,done})."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    side = dest.with_suffix(dest.suffix + ".gogpart")

    ranges = None
    if side.exists() and dest.exists() and dest.stat().st_size == size:
        try:
            saved = json.loads(side.read_text())
            if saved.get("size") == size and saved.get("ranges"):
                ranges = saved["ranges"]
        except Exception:
            ranges = None
    if ranges is None:
        step = size // segments
        ranges = []
        for i in range(segments):
            start = i * step
            end   = (size - 1) if i == segments - 1 else (start + step - 1)
            ranges.append({"start": start, "end": end, "done": 0})
        with open(dest, "wb") as fh:           # pre-allocate
            fh.truncate(size)

    # Probe once whether the CDN honours byte ranges. Some GOG secure links
    # ignore the Range header and answer 200 with the *whole* file — if we then
    # ran N parallel seekers, each would write the full file at its own offset
    # and the result would be corrupt (MD5 mismatch). Fall back to a single
    # clean stream in that case.
    try:
        probe   = _open_response(cdn_url, f"bytes=0-{ranges[0]['end']}")
        pstatus = getattr(probe, "status", probe.getcode())
        try:
            probe.close()
        except Exception:
            pass
    except Exception:
        pstatus = None
    if pstatus != 206:
        log(f"segmented: serwer nie wspiera Range (status {pstatus}) — "
            f"pobieram jednym połączeniem: {dest.name}")
        try:
            side.unlink()
        except Exception:
            pass
        with open(dest, "wb") as fh:           # reset the pre-allocated file
            fh.truncate(0)
        _download_stream(cdn_url, dest, sid, hub)
        return

    counter = {"got": sum(r["done"] for r in ranges)}
    clock   = threading.Lock()
    last_save = {"t": 0.0}

    def save_side():
        try:
            side.write_text(json.dumps({"size": size, "ranges": ranges}))
        except Exception:
            pass

    def seg_worker(r):
        start = r["start"] + r["done"]
        if start > r["end"]:
            return
        resp   = _open_response(cdn_url, f"bytes={start}-{r['end']}")
        status = getattr(resp, "status", resp.getcode())
        if status != 206:
            # Range ignored on this connection — refuse to write (would clobber
            # other segments). Signals the caller to retry as a single stream.
            raise _RangeUnsupported(f"status {status} dla zakresu {start}-{r['end']}")
        remaining = r["end"] - start + 1          # never write past this range
        with open(dest, "r+b") as fh:
            fh.seek(start)
            while remaining > 0:
                if _cancel.is_set():
                    raise RuntimeError("anulowano")
                chunk = resp.read(min(1024 * 256, remaining))
                if not chunk:
                    break
                fh.write(chunk)
                n = len(chunk)
                r["done"]  += n
                remaining  -= n
                with clock:
                    counter["got"] += n
                    now = time.time()
                    if now - last_save["t"] > 1.0:
                        last_save["t"] = now
                        save_side()
                hub.progress(sid, counter["got"])

    errors = []
    threads = []
    for r in ranges:
        t = threading.Thread(target=_seg_run, args=(seg_worker, r, errors), daemon=True)
        threads.append(t); t.start()
    for t in threads:
        t.join()
    if errors:
        # If any segment found ranges unsupported, redo the whole file cleanly.
        if any(isinstance(e, _RangeUnsupported) for e in errors) and not _cancel.is_set():
            log(f"segmented: zakresy niespójne — ponawiam jednym połączeniem: {dest.name}")
            try:
                side.unlink()
            except Exception:
                pass
            with open(dest, "wb") as fh:
                fh.truncate(0)
            _download_stream(cdn_url, dest, sid, hub)
            return
        save_side()
        raise errors[0]
    try:
        side.unlink()
    except Exception:
        pass


class _RangeUnsupported(Exception):
    """Raised when a CDN connection ignores the Range header (answers 200)."""


def _seg_run(fn, r, errors):
    try:
        fn(r)
    except Exception as exc:
        errors.append(exc)


def _verify_md5(dest: Path, checksum_url: str, box: dict) -> bool | None:
    """Return True/False, or None if no checksum available to compare."""
    try:
        xml_text = urllib.request.urlopen(
            urllib.request.Request(checksum_url, headers={"User-Agent": "Mozilla/5.0"}),
            timeout=30).read().decode("utf-8", "replace")
    except Exception as exc:
        log(f"checksum fetch failed: {exc}")
        return None
    want = _md5_from_checksum_xml(xml_text)
    if not want:
        return None
    return _md5_path(dest).lower() == want.lower()


def _remote_md5(checksum_url: str) -> str | None:
    """Whole-file MD5 from a GOG checksum XML, or None if unavailable (GOG serves
    no checksums for most bonus content — the .xml 404s)."""
    try:
        xml_text = urllib.request.urlopen(
            urllib.request.Request(checksum_url, headers={"User-Agent": "Mozilla/5.0"}),
            timeout=30).read().decode("utf-8", "replace")
    except Exception:
        return None
    return _md5_from_checksum_xml(xml_text)


def _md5_path(p: Path) -> str:
    """MD5 of a file on disk, streamed (cancel-aware)."""
    h = hashlib.md5()
    with open(p, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            if _cancel.is_set():
                raise RuntimeError("anulowano")
            h.update(block)
    return h.hexdigest()


def _md5_bytes(data: bytes) -> str:
    h = hashlib.md5()
    h.update(data)
    return h.hexdigest()


def _fetch_to_ram(cdn_url: str, hub: "_ProgressHub | None" = None,
                  sid=None, name: str = "") -> bytes:
    """Download a whole file into memory (no disk write), cancel-aware. Used to
    verify no-checksum files by content: fetch → compare → keep or replace."""
    resp  = _open_response(cdn_url)
    total = int(resp.headers.get("Content-Length") or 0)
    if hub is not None:
        hub.start(sid, name, total)
    buf = bytearray()
    while True:
        if _cancel.is_set():
            raise RuntimeError("anulowano")
        chunk = resp.read(1024 * 256)
        if not chunk:
            break
        buf.extend(chunk)
        if hub is not None:
            hub.progress(sid, len(buf))
    return bytes(buf)


def _download_unit(unit: dict, segments: int, hub: _ProgressHub,
                   box: dict, slot_pool: "queue.Queue") -> tuple:
    if _cancel.is_set():
        return ("err", unit, "anulowano")
    sid = slot_pool.get()
    completed = False
    try:
        info     = _resolve_downlink(unit["downlink"], box)
        cdn      = info.get("downlink")
        checksum = info.get("checksum")
        if not cdn:
            return ("err", unit, "brak downlink")
        fname = _filename_from_url(cdn)
        dest  = unit["dest_dir"] / fname
        size  = unit["size"] or 0
        hub.start(sid, fname, size)

        if unit.get("fresh"):
            # Replacing a stale/changed file: start from scratch so resume logic
            # can never append new bytes onto old (wrong) content.
            for p in (dest, dest.with_suffix(dest.suffix + ".gogpart")):
                try:
                    p.unlink()
                except FileNotFoundError:
                    pass
                except Exception as exc:
                    log(f"fresh unlink {p}: {exc}")

        if segments > 1 and size >= _SEGMENT_MIN_BYTES:
            _download_segmented(cdn, dest, size, segments, sid, hub)
        else:
            _download_stream(cdn, dest, sid, hub)

        completed = True
        _send_js({"type": "completion", "filename": fname, "speed": "OK"})

        if unit["verify"] and checksum:
            res = _verify_md5(dest, checksum, box)
            if res is True:
                _push_log(f"✓ MD5 OK: {fname}")
            elif res is False:
                _push_log(f"✗ MD5 NIE pasuje: {fname} — plik może być uszkodzony.")
                return ("bad", unit, fname)
        return ("ok", unit, fname)
    except Exception as exc:
        return ("err", unit, str(exc))
    finally:
        hub.finish(sid, completed)
        slot_pool.put(sid)


def _download_worker(game_id, selection_keys: list) -> bool:
    g = next((x for x in scan_games() if x["id"] == str(game_id)), None)
    if not g:
        _push_log("✗ Gra nie znaleziona.")
        return False

    installed = scan_installed_games()
    if g["id"] in installed:
        _push_log(f"✗ Gra jest już zainstalowana: {installed[g['id']]}")
        return False

    man  = get_download_manifest(game_id)
    rows = (man.get("installers", []) + man.get("patches", []) +
            man.get("language_packs", []) + man.get("dlcs", []) +
            man.get("extras", []))
    by_key = {r["key"]: r for r in rows}
    chosen = [by_key[k] for k in selection_keys if k in by_key]
    if not chosen:
        _push_log("✗ Nic nie zaznaczono.")
        return False
    return _download_selection(g, chosen)


def _download_selection(g: dict, chosen: list) -> bool:
    """Download the given manifest rows (installers/patches/extras/…) for game g
    into BASE/<slug>.  Shared by the classic download path and the depot-install
    extras phase."""
    dest_dir   = BASE / g["slug"]
    extras_dir = dest_dir / "extras" if get_settings().get("extras_subdir", True) else dest_dir
    units = []
    for row in chosen:
        row_dest = extras_dir if row.get("category") == "extra" else dest_dir
        for part in row["parts"]:
            units.append({"downlink": part["downlink"], "size": part.get("size") or 0,
                          "verify": bool(row.get("verify")), "name": row["name"],
                          "dest_dir": row_dest})
    grand = sum(u["size"] for u in units)
    nfiles = len(units)

    # Free-space guard
    try:
        free = shutil.disk_usage(str(BASE if BASE.exists() else BASE.anchor)).free
        if grand and free < grand:
            _push_log(f"✗ Za mało miejsca: potrzeba {_human(grand)}, wolne {_human(free)}.")
            return False
    except Exception:
        pass

    # Shared connection budget → parallel files vs single-file segments.
    conn = get_download_threads()
    if nfiles >= conn:
        file_workers, segments = conn, 1
    else:
        file_workers = max(1, nfiles)
        segments     = max(1, conn // max(1, nfiles))

    _push_log(f"Pobieram do {dest_dir} — {nfiles} plików, {_human(grand)}; "
              f"{conn} połączeń ({file_workers} plik(i) × {segments} segment(ów)).")

    hub  = _ProgressHub(grand)
    pool = queue.Queue()
    for i in range(1, file_workers + 1):
        pool.put(i)
    box = _access_token_box()

    results = []
    with ThreadPoolExecutor(max_workers=file_workers) as ex:
        futs = [ex.submit(_download_unit, u, segments, hub, box, pool) for u in units]
        for fu in as_completed(futs):
            results.append(fu.result())

    if _cancel.is_set():
        _push_log("⚠ Przerwano przez użytkownika.")
        return False

    ok  = sum(1 for s, _, _ in results if s == "ok")
    bad = sum(1 for s, _, _ in results if s in ("bad", "err"))
    for s, u, msg in results:
        if s == "err":
            _push_log(f"✗ Błąd przy {u['name']}: {msg}")
    _push_log(f"✓ Zakończono: {ok} plików OK" + (f", {bad} z problemem" if bad else "") + ".")
    return bad == 0


def _installed_dlc_ids(game_id) -> list:
    """DLC already installed for a game = goggame-{id}.info files present in its
    install dir, other than the base product id."""
    g = next((x for x in scan_games() if x["id"] == str(game_id)), None)
    if not g:
        return []
    base_pid = str(g["product"].get("id") or "")
    install_dir = scan_installed_games().get(str(game_id))
    if not install_dir:
        return []
    out = []
    for info in Path(install_dir).glob("goggame-*.info"):
        m = re.match(r"goggame-(\d+)\.info$", info.name)
        if m and m.group(1) != base_pid:
            out.append(m.group(1))
    return out


def get_downloads(game_id) -> dict:
    man = get_download_manifest(game_id)
    if man.get("ok"):
        man["installed"]     = bool(scan_installed_games().get(str(game_id)))
        man["installed_dlc"] = _installed_dlc_ids(game_id)
    return man


# ── depot install (Galaxy content-system v2) ──────────────────────────────────
# Installs the game the way GOG Galaxy does: build meta → depot manifests →
# ~10 MB zlib chunks assembled straight into the game directory.  No offline
# installer is downloaded at all.


def _galaxy_path(h: str) -> str:
    return f"{h[0:2]}/{h[2:4]}/{h}"


def _cs_get_zlib(url: str) -> dict:
    """Fetch a zlib-compressed JSON manifest from the GOG CDN."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read()
    try:
        raw = zlib.decompress(raw, 15)
    except zlib.error:
        pass                                   # some mirrors serve it plain
    return json.loads(raw.decode("utf-8", "replace"))


def _authed_json(url: str, box: dict) -> dict:
    """GET JSON with Bearer auth, refreshing the token once on 401/403.
    Same semantics as _resolve_downlink but reusable for content-system calls."""
    try:
        return _gog_get_json(url, box["access"])
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403) and box.get("refresh"):
            with box["lock"]:
                try:
                    return _gog_get_json(url, box["access"])
                except urllib.error.HTTPError as exc2:
                    if exc2.code not in (401, 403):
                        raise
                _push_log("Token wygasł — odświeżam…")
                new = _refresh_access_token(box["refresh"])
                box["access"] = new.get("access_token")
                for k in ("access_token", "refresh_token", "expires_in", "expires_at",
                          "session_id", "token_type", "scope", "user_id"):
                    if k in new:
                        box["tokens"][k] = new[k]
                _write_galaxy_tokens(box["tokens"])
            return _gog_get_json(url, box["access"])
        raise


def _get_secure_link(product_id: str, box: dict) -> str:
    """Resolve the CDN secure link template for chunk downloads."""
    js = _authed_json(GOG_SECURE_LINK.format(id=product_id), box)
    urls = js.get("urls") or []
    if not urls:
        raise RuntimeError("secure_link: pusta lista CDN")
    # Prefer a fastly endpoint, otherwise take the first usable one.
    urls.sort(key=lambda u: 0 if "fastly" in (u.get("endpoint_name") or "") else 1)
    ep = next((u for u in urls if u.get("url_format") and u.get("parameters")), None)
    if not ep:
        raise RuntimeError("secure_link: brak użytecznego endpointu")
    link = ep["url_format"]
    for k, v in ep["parameters"].items():
        link = link.replace("{" + k + "}", str(v))
    return link


def _fetch_chunk(secure_link: str, comp_md5: str) -> bytes:
    """Download one chunk, verify its compressed MD5, return decompressed bytes."""
    url = f"{secure_link}/{_galaxy_path(comp_md5)}"
    last_exc = None
    for attempt in range(3):
        if _cancel.is_set():
            raise RuntimeError("anulowano")
        try:
            with _open_response(url) as resp:
                data = resp.read()
            if hashlib.md5(data).hexdigest().lower() != comp_md5.lower():
                raise RuntimeError(f"MD5 chunku nie pasuje ({comp_md5[:8]}…)")
            return zlib.decompress(data, 15)
        except Exception as exc:
            last_exc = exc
            time.sleep(1 + attempt)
    raise last_exc


def _pick_build(product_id: str) -> dict:
    # The builds endpoint returns plain JSON (unlike the zlib CDN manifests).
    req = urllib.request.Request(GOG_BUILDS_API.format(id=product_id),
                                 headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        js = json.loads(resp.read().decode("utf-8", "replace"))
    items = js.get("items") or []
    # Newest non-beta branch build first (items come newest-first from the API).
    for it in items:
        if not it.get("branch"):
            return it
    if items:
        return items[0]
    raise RuntimeError("Brak buildów Galaxy (generation=2) dla Windows")


def _dependency_secure_link() -> str:
    """CDN link template for redist (dependency) chunk downloads — no auth needed."""
    req = urllib.request.Request(GOG_DEP_STORE_LINK, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        js = json.loads(resp.read().decode("utf-8", "replace"))
    urls = js.get("urls") or []
    if not urls:
        raise RuntimeError("dependencies: pusta lista CDN")
    urls.sort(key=lambda u: 0 if "fastly" in (u.get("endpoint_name") or "") else 1)
    ep = urls[0]
    link = ep.get("url_format") or ""
    for k, v in (ep.get("parameters") or {}).items():
        link = link.replace("{" + k + "}", str(v))
    if not link:
        raise RuntimeError("dependencies: brak url_format")
    return link


def _dependency_items(dep_ids: list) -> tuple[list, list, set]:
    """Resolve declared redist dependency ids (e.g. 'DOSBox074_2CS') to the
    DepotFile / DepotDirectory items that must be unpacked into the game dir.
    Returns (files, dirs, missing_ids)."""
    want = {str(d) for d in (dep_ids or []) if str(d).strip()}
    if not want:
        return [], [], set()
    repo = _cs_get_zlib(GOG_DEP_REPO)          # plain JSON; _cs_get_zlib tolerates that
    man_url = repo.get("repository_manifest")
    if not man_url:
        raise RuntimeError("brak repository_manifest")
    rep = _cs_get_zlib(man_url)
    files, dirs, matched = [], [], set()
    for d in rep.get("depots") or []:
        did = str(d.get("dependencyId") or "")
        if did not in want or not d.get("manifest"):
            continue
        matched.add(did)
        man = _cs_get_zlib(
            f"{GOG_CDN}/content-system/v2/dependencies/meta/{_galaxy_path(d['manifest'])}")
        for it in (man.get("depot") or {}).get("items") or []:
            t = it.get("type")
            if t == "DepotDirectory":
                dirs.append(it)
            elif t == "DepotFile":
                files.append(it)
    return files, dirs, (want - matched)


def _apply_support_data(install_dir: Path, pid: str) -> None:
    """Replay the 'supportData' file/folder copies from goggame-{pid}.script.
    GOG's installer copies DOSBox/ScummVM .conf files out of a support subfolder
    (usually 'app\\') into the game root so the playTasks arguments like
    '-conf "..\\dosboxXX.conf"' resolve.  Depot installs bypass that installer,
    so without this the runtime has no config and the game won't start."""
    scr = install_dir / f"goggame-{pid}.script"
    if not scr.exists():
        scr = next(install_dir.glob("goggame-*.script"), None)
    if not scr or not scr.exists():
        return

    def _resolve(s: str) -> Path:
        s = (s or "").replace("{app}", str(install_dir)) \
                     .replace("{supportDir}", str(install_dir))
        return Path(s.replace("/", os.sep).replace("\\", os.sep))

    try:
        data = json.loads(scr.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        log(f"support script parse: {exc}")
        return
    for act in data.get("actions") or []:
        ins = act.get("install") or {}
        if ins.get("action") != "supportData":
            continue
        args = ins.get("arguments") or {}
        typ  = (args.get("type") or "").lower()
        src  = _resolve(args.get("source"))
        dst  = _resolve(args.get("target"))
        try:
            if typ == "folder" and src.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=True)
                log(f"supportData: folder {src} → {dst}")
            elif typ == "file" and src.is_file():
                target = (dst / src.name) if (dst.is_dir() or not dst.suffix) else dst
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, target)
                log(f"supportData: plik {src} → {target}")
        except Exception as exc:
            log(f"supportData copy error ({src}→{dst}): {exc}")


def _norm_lang(code: str) -> str:
    """GOG language code → short prefix, e.g. 'en-US' → 'en', 'zh-Hans' → 'zh'."""
    return str(code or "").lower().replace("_", "-").split("-")[0]


def _lang_match(langs: list, wanted: set | None = None) -> bool:
    """A depot is wanted if it is language-neutral ('*') or carries one of the
    `wanted` languages (prefix match, e.g. 'pl' ↔ 'pl-PL'). `wanted` defaults to
    English so old call sites keep working."""
    want = {str(w).lower() for w in (wanted or {"en"})}
    for l in (langs or []):
        if l == "*":
            return True
        if _norm_lang(l) in want:
            return True
    return False


def _depot_langs_setting() -> list:
    v = get_settings().get("depot_langs")
    return [str(x).lower() for x in v] if isinstance(v, list) and v else ["en"]


def get_build_languages(game_id) -> dict:
    """Languages actually available in a game's Galaxy build depots (for the UI
    to offer a real choice). Returns {ok, languages:[codes], has_build}."""
    g = next((x for x in scan_games() if x["id"] == str(game_id)), None)
    if not g:
        return {"ok": False, "error": "Gra nie znaleziona"}
    pid = str(g["product"].get("id") or "").strip()
    try:
        build = _pick_build(pid)
        meta  = _cs_get_zlib(build["link"])
    except Exception as exc:
        return {"ok": False, "error": str(exc), "has_build": False}
    langs = set()
    for d in meta.get("depots") or []:
        for l in d.get("languages") or []:
            if l and l != "*":
                langs.add(_norm_lang(l))
    return {"ok": True, "has_build": True, "languages": sorted(langs)}


def _read_depot_state(install_dir: Path, build_id: str) -> set:
    p = install_dir / _DEPOT_STATE_NAME
    try:
        st = json.loads(p.read_text(encoding="utf-8"))
        if st.get("build_id") == build_id:
            return set(st.get("done") or [])
    except Exception:
        pass
    return set()


def _write_depot_state(install_dir: Path, build_id: str, done: set) -> None:
    try:
        (install_dir / _DEPOT_STATE_NAME).write_text(
            json.dumps({"build_id": build_id, "done": sorted(done)}),
            encoding="utf-8")
    except Exception:
        pass


def _install_dlc_via_depots(meta: dict, dlc_ids: set, install_dir: Path,
                            base_pid: str, box: dict, hub: "_ProgressHub",
                            conn: int, wanted: set | None = None) -> tuple[bool, set]:
    """Install selected DLC INTO the game directory from the build's DLC depots
    (the way GOG Galaxy does), instead of dropping a separate offline installer
    in GOGinstall. DLC are separate products, so each depot's chunks use that
    DLC's own secure link. `wanted` = languages to install. Returns
    (ok, {installed_dlc_ids})."""
    all_depots = meta.get("depots") or []
    ok_all, installed = True, set()

    for did in sorted(dlc_ids):
        depots = [d for d in all_depots if str(d.get("productId")) == str(did)]
        chosen = [d for d in depots if _lang_match(d.get("languages"), wanted)] or depots
        if not chosen:
            _push_log(f"⚠ DLC {did}: brak depotów w tym buildzie — pomijam.")
            continue

        files, dirs, sfc = [], [], None
        try:
            for d in chosen:
                man = _cs_get_zlib(f"{GOG_CDN}/content-system/v2/meta/{_galaxy_path(d['manifest'])}")
                dep = man.get("depot") or {}
                for it in dep.get("items") or []:
                    t = it.get("type")
                    if t == "DepotDirectory":
                        dirs.append(it)
                    elif t == "DepotFile":
                        files.append(it)
                if dep.get("smallFilesContainer") and sfc is None:
                    sfc = dep["smallFilesContainer"]
        except Exception as exc:
            _push_log(f"✗ DLC {did}: manifest depotu: {exc}")
            ok_all = False
            continue

        try:
            secure = _get_secure_link(str(did), box)
        except Exception as exc:
            _push_log(f"✗ DLC {did}: secure_link: {exc}")
            ok_all = False
            continue

        for it in dirs:
            (install_dir / it["path"].replace("\\", "/").lstrip("/")).mkdir(
                parents=True, exist_ok=True)

        plain = [f for f in files if not f.get("sfcRef")]
        sfced = [f for f in files if f.get("sfcRef")]
        total = sum(sum(c.get("size") or 0 for c in f.get("chunks") or []) for f in plain)
        total += sum(c.get("size") or 0 for c in (sfc.get("chunks") if sfc else []) or [])
        _push_log(f"Instaluję DLC {did}: {len(files)} plików, {_human(total)}…")

        sid = 90000 + (abs(hash(str(did))) % 1000)
        hub.start(sid, f"DLC {did}", total)
        got, clk = {"n": 0}, threading.Lock()

        def bump(n, _sid=sid):
            with clk:
                got["n"] += n
            hub.progress(_sid, got["n"])

        jobs = []
        for f in plain:
            rel  = f["path"].replace("\\", "/").lstrip("/")
            dest = install_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            chunks = f.get("chunks") or []
            if not chunks:
                dest.touch(exist_ok=True)
                continue
            with open(dest, "wb") as fh:
                fh.truncate(sum(c.get("size") or 0 for c in chunks))
            off = 0
            for c in chunks:
                jobs.append((dest, off, c))
                off += c.get("size") or 0

        errs = []

        def cj(dest, off, c):
            if _cancel.is_set() or errs:
                return
            try:
                data = _fetch_chunk(secure, c["compressedMd5"])
                with open(dest, "r+b") as fh:
                    fh.seek(off)
                    fh.write(data)
                bump(len(data))
            except Exception as exc:
                errs.append(exc)

        if jobs:
            with ThreadPoolExecutor(max_workers=conn) as ex:
                for fu in as_completed([ex.submit(cj, *j) for j in jobs]):
                    fu.result()

        if sfced and sfc and not errs and not _cancel.is_set():
            tmp = install_dir / f"__gog_sfc_{did}.tmp"
            try:
                with open(tmp, "wb") as fh:
                    for c in sfc.get("chunks") or []:
                        fh.write(_fetch_chunk(secure, c["compressedMd5"]))
                        bump(c.get("size") or 0)
                with open(tmp, "rb") as fh:
                    for f in sfced:
                        rel  = f["path"].replace("\\", "/").lstrip("/")
                        dest = install_dir / rel
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        ref = f["sfcRef"]
                        fh.seek(ref["offset"])
                        dest.write_bytes(fh.read(ref["size"]))
            except Exception as exc:
                errs.append(exc)
            finally:
                try:
                    tmp.unlink()
                except Exception:
                    pass

        hub.finish(sid, not errs)
        if _cancel.is_set():
            return (False, installed)
        if errs:
            _push_log(f"✗ DLC {did}: {errs[0]}")
            ok_all = False
            continue

        # goggame-{dlc}.info so the game/Galaxy recognizes the DLC as installed.
        info = install_dir / f"goggame-{did}.info"
        if not info.exists():
            try:
                info.write_text(json.dumps({
                    "gameId": str(did), "rootGameId": str(base_pid),
                    "name": f"DLC {did}", "playTasks": [],
                }, indent=2), encoding="utf-8")
            except Exception as exc:
                log(f"dlc info write {did}: {exc}")
        installed.add(str(did))
        _push_log(f"✓ DLC {did} zainstalowane.")

    return (ok_all, installed)


def _depot_install_worker(game_id, extra_keys: list, langs: list | None = None) -> bool:
    g = next((x for x in scan_games() if x["id"] == str(game_id)), None)
    if not g:
        _push_log("✗ Gra nie znaleziona.")
        return False
    wanted = {str(l).lower() for l in (langs or _depot_langs_setting())}
    installed = scan_installed_games()
    if g["id"] in installed:
        _push_log(f"✗ Gra jest już zainstalowana: {installed[g['id']]}")
        return False
    pid = str(g["product"].get("id") or "").strip()
    if not pid:
        _push_log("✗ Brak product_id.")
        return False

    box = _access_token_box()
    if not box.get("access"):
        _push_log("✗ Brak logowania GOG — zaloguj się w Ustawieniach.")
        return False

    # 1. Build meta ------------------------------------------------------------
    _push_log("Pobieram listę buildów Galaxy…")
    try:
        build = _pick_build(pid)
        meta  = _cs_get_zlib(build["link"])
    except Exception as exc:
        _push_log(f"✗ Nie udało się pobrać manifestu builda: {exc}")
        return False
    build_id    = str(build.get("build_id") or meta.get("buildId") or "")
    version     = build.get("version_name") or ""
    install_sub = meta.get("installDirectory") or g["slug"]
    install_dir = GOG_GAMES / install_sub
    _push_log(f"Build {build_id} {('v' + version) if version else ''} → {install_dir}")

    deps = meta.get("dependencies") or []
    if deps:
        _push_log(f"Gra deklaruje zależności (redist): {', '.join(map(str, deps))} — "
                  "zainstaluję je po plikach gry.")

    # 2. Depot manifests (base game, chosen languages + language-neutral) -------
    _push_log(f"Języki instalacji: {', '.join(sorted(wanted))}")
    depots = [d for d in (meta.get("depots") or []) if str(d.get("productId")) == pid]
    chosen_depots = [d for d in depots if _lang_match(d.get("languages"), wanted)]
    if not chosen_depots:
        chosen_depots = depots
        _push_log("⚠ Brak depotów dla wybranych języków — instaluję wszystkie depoty gry bazowej.")
    if not chosen_depots:
        _push_log("✗ Manifest nie zawiera depotów gry bazowej.")
        return False

    files, dirs, sfc = [], [], None
    try:
        for d in chosen_depots:
            man = _cs_get_zlib(f"{GOG_CDN}/content-system/v2/meta/{_galaxy_path(d['manifest'])}")
            dep = man.get("depot") or {}
            for it in dep.get("items") or []:
                t = it.get("type")
                if t == "DepotDirectory":
                    dirs.append(it)
                elif t == "DepotFile":
                    files.append(it)
                else:
                    log(f"depot: pomijam element typu {t}: {it.get('path')}")
            if dep.get("smallFilesContainer") and sfc is None:
                sfc = dep["smallFilesContainer"]
    except Exception as exc:
        _push_log(f"✗ Błąd pobierania manifestów depotów: {exc}")
        return False

    plain   = [f for f in files if not f.get("sfcRef")]
    sfced   = [f for f in files if f.get("sfcRef")]
    total   = sum(sum(c.get("size") or 0 for c in f.get("chunks") or []) for f in plain)
    total  += sum(c.get("size") or 0 for c in (sfc.get("chunks") if sfc else []) or [])
    _push_log(f"Do zainstalowania: {len(files)} plików, {_human(total)} "
              f"({len(chosen_depots)} depot(y), {len(sfced)} w kontenerze SFC).")

    # Free-space guard on the games drive.
    try:
        anchor = install_dir if install_dir.exists() else Path(install_dir.anchor)
        free = shutil.disk_usage(str(anchor)).free
        if total and free < total:
            _push_log(f"✗ Za mało miejsca: potrzeba {_human(total)}, wolne {_human(free)}.")
            return False
    except Exception:
        pass

    # 3. Prepare directory tree + resume state ---------------------------------
    install_dir.mkdir(parents=True, exist_ok=True)
    for d in dirs:
        (install_dir / d["path"].replace("\\", "/")).mkdir(parents=True, exist_ok=True)
    done = _read_depot_state(install_dir, build_id)
    if done:
        _push_log(f"Wznawiam — {len(done)} plików już ukończonych.")

    try:
        secure = _get_secure_link(pid, box)
    except Exception as exc:
        _push_log(f"✗ secure_link: {exc}")
        return False

    hub = _ProgressHub(total)
    hub.start(1, f"Instalacja: {g['title']}", total)
    counter = {"got": sum(sum(c.get("size") or 0 for c in f.get("chunks") or [])
                          for f in plain if f["path"] in done)}
    clock = threading.Lock()
    state_lock = threading.Lock()

    def bump(n: int):
        with clock:
            counter["got"] += n
        hub.progress(1, counter["got"])

    # 4. Regular files — flat chunk job list, shared connection budget ----------
    jobs = []            # (path_str, dest, offset, chunk)
    remaining = {}       # path_str -> chunk count
    for f in plain:
        rel  = f["path"].replace("\\", "/").lstrip("/")
        dest = install_dir / rel
        chunks = f.get("chunks") or []
        size   = sum(c.get("size") or 0 for c in chunks)
        if rel in done:
            continue
        if not chunks:                       # empty file
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.touch(exist_ok=True)
            done.add(rel)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as fh:         # pre-allocate
            fh.truncate(size)
        off = 0
        for c in chunks:
            jobs.append((rel, dest, off, c))
            off += c.get("size") or 0
        remaining[rel] = len(chunks)

    conn = get_download_threads()
    err_box = []

    def chunk_job(rel, dest, off, c):
        if _cancel.is_set() or err_box:
            return
        try:
            data = _fetch_chunk(secure, c["compressedMd5"])
            with open(dest, "r+b") as fh:
                fh.seek(off)
                fh.write(data)
            bump(len(data))
            with state_lock:
                remaining[rel] -= 1
                if remaining[rel] == 0:
                    done.add(rel)
                    _write_depot_state(install_dir, build_id, done)
        except Exception as exc:
            err_box.append((rel, exc))

    ok = True
    if jobs:
        _push_log(f"Pobieram {len(jobs)} chunków ({conn} połączeń)…")
        with ThreadPoolExecutor(max_workers=conn) as ex:
            futs = [ex.submit(chunk_job, *j) for j in jobs]
            for fu in as_completed(futs):
                fu.result()
    if _cancel.is_set():
        _write_depot_state(install_dir, build_id, done)
        hub.finish(1, False)
        _push_log("⚠ Przerwano — postęp zapisany, instalację można wznowić.")
        return False
    if err_box:
        _write_depot_state(install_dir, build_id, done)
        hub.finish(1, False)
        for rel, exc in err_box[:5]:
            _push_log(f"✗ {rel}: {exc}")
        _push_log("✗ Instalacja niekompletna — uruchom ponownie, aby wznowić.")
        return False

    # 5. Small Files Container --------------------------------------------------
    if sfced:
        if not sfc:
            _push_log("✗ Pliki wskazują na kontener SFC, ale manifest go nie zawiera.")
            ok = False
        else:
            _push_log(f"Składam kontener małych plików ({len(sfced)} plików)…")
            tmp = install_dir / "__gog_sfc.tmp"
            try:
                with open(tmp, "wb") as fh:
                    for c in sfc.get("chunks") or []:
                        fh.write(_fetch_chunk(secure, c["compressedMd5"]))
                        bump(c.get("size") or 0)
                with open(tmp, "rb") as fh:
                    for f in sfced:
                        rel  = f["path"].replace("\\", "/").lstrip("/")
                        dest = install_dir / rel
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        ref = f["sfcRef"]
                        fh.seek(ref["offset"])
                        dest.write_bytes(fh.read(ref["size"]))
                        done.add(rel)
            except Exception as exc:
                _push_log(f"✗ SFC: {exc}")
                ok = False
            finally:
                try: tmp.unlink()
                except Exception: pass

    # 5b. Redist dependencies (DOSBox / ScummVM / … — DOS & wrapped games) -------
    # Native Windows games declare none; DOS games ship their runtime here, so
    # skipping this left only the data blob with no DOSBox.exe to launch it.
    if ok and deps:
        try:
            dep_files, dep_dirs, dep_missing = _dependency_items(deps)
        except Exception as exc:
            _push_log(f"✗ Zależności — nie pobrano repozytorium: {exc}")
            dep_files, dep_dirs, dep_missing = [], [], {str(d) for d in deps}
        if dep_missing:
            _push_log("⚠ Zależności nieznalezione w repozytorium: "
                      f"{', '.join(sorted(dep_missing))} — doinstaluj je ręcznie.")
        if dep_files:
            _push_log(f"Instaluję zależności ({len(dep_files)} plików)…")
            for it in dep_dirs:
                (install_dir / it["path"].replace("\\", "/").lstrip("/")).mkdir(
                    parents=True, exist_ok=True)
            try:
                dep_secure = _dependency_secure_link()
            except Exception as exc:
                _push_log(f"✗ secure_link zależności: {exc}")
                dep_secure, ok = None, False
            if dep_secure:
                dep_jobs = []
                for f in dep_files:
                    rel  = f["path"].replace("\\", "/").lstrip("/")
                    dest = install_dir / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    chunks = f.get("chunks") or []
                    if not chunks:
                        dest.touch(exist_ok=True)
                    else:
                        dep_jobs.append((dest, chunks))

                dep_err = []

                def dep_job(dest, chunks):
                    if _cancel.is_set() or dep_err:
                        return
                    try:
                        with open(dest, "wb") as fh:
                            for c in chunks:
                                fh.write(_fetch_chunk(dep_secure, c["compressedMd5"]))
                    except Exception as exc:
                        dep_err.append((dest.name, exc))

                with ThreadPoolExecutor(max_workers=conn) as ex:
                    futs = [ex.submit(dep_job, d, c) for d, c in dep_jobs]
                    for fu in as_completed(futs):
                        fu.result()
                if _cancel.is_set():
                    _write_depot_state(install_dir, build_id, done)
                    hub.finish(1, False)
                    _push_log("⚠ Przerwano na zależnościach — instalację można wznowić.")
                    return False
                if dep_err:
                    ok = False
                    for name, exc in dep_err[:5]:
                        _push_log(f"✗ zależność {name}: {exc}")
                else:
                    _push_log("✓ Zależności zainstalowane.")

    hub.finish(1, ok)
    if not ok:
        _write_depot_state(install_dir, build_id, done)
        return False

    # 6. Support data (DOSBox/ScummVM .conf → game root) so the game can launch --
    _apply_support_data(install_dir, pid)

    # 6b. goggame info so the library detects the install -----------------------
    info = install_dir / f"goggame-{pid}.info"
    if not info.exists():
        try:
            info.write_text(json.dumps({
                "gameId": pid, "rootGameId": pid, "name": g["title"],
                "buildId": build_id, "version": version, "playTasks": [],
            }, indent=2), encoding="utf-8")
        except Exception as exc:
            log(f"goggame info write: {exc}")
    try:
        (install_dir / _DEPOT_STATE_NAME).unlink()
    except Exception:
        pass
    _send_js({"type": "completion", "filename": f"{g['title']} — zainstalowano", "speed": "OK"})
    _push_log(f"✓ Zainstalowano (depot v2): {install_dir}")
    _push_log("ℹ Instalacja bez instalatora nie tworzy wpisów rejestru ani skrótów — "
              "większości gier GOG to nie przeszkadza.")

    # 6c. Selected DLC — installed INTO the game dir from their depots -----------
    dlc_ids = {k.split(":")[1] for k in (extra_keys or [])
               if isinstance(k, str) and k.startswith("dlc:") and len(k.split(":")) > 1 and k.split(":")[1]}
    if dlc_ids:
        _push_log(f"Instaluję zaznaczone DLC ({len(dlc_ids)}) z depotów…")
        dlc_ok, _ = _install_dlc_via_depots(meta, dlc_ids, install_dir, pid, box,
                                            hub, get_download_threads(), wanted)
        if not dlc_ok:
            _push_log("⚠ Część DLC nie zainstalowała się poprawnie.")

    # 7. Optional extras / language packs via the classic downlink path ----------
    #    (DLC are handled above as depots — never as offline installers here.)
    non_dlc_keys = [k for k in (extra_keys or [])
                    if not (isinstance(k, str) and k.startswith("dlc:"))]
    if non_dlc_keys:
        man  = get_download_manifest(game_id)
        rows = man.get("extras", []) + man.get("language_packs", [])
        by_key = {r["key"]: r for r in rows}
        chosen = [by_key[k] for k in non_dlc_keys if k in by_key]
        if chosen:
            _push_log(f"Pobieram dodatki ({len(chosen)} poz.)…")
            if not _download_selection(g, chosen):
                _push_log("⚠ Gra zainstalowana, ale część dodatków nie pobrała się poprawnie.")
    return True


def install_game(game_id, extra_keys=None, langs=None) -> dict:
    keys = extra_keys if isinstance(extra_keys, list) else []
    langs = langs if isinstance(langs, list) else None
    return _submit_task(lambda: _depot_install_worker(game_id, keys, langs),
                        _task_label("Instalacja", game_id), queueable=True)


def _install_dlc_worker(game_id, dlc_keys: list, langs: list | None = None) -> bool:
    """Add selected DLC (from their depots) into an ALREADY-installed game."""
    g = next((x for x in scan_games() if x["id"] == str(game_id)), None)
    if not g:
        _push_log("✗ Gra nie znaleziona.")
        return False
    pid = str(g["product"].get("id") or "").strip()
    install_dir = scan_installed_games().get(g["id"])
    if not install_dir:
        _push_log("✗ Gra nie jest zainstalowana — najpierw zainstaluj grę.")
        return False
    install_dir = Path(install_dir)

    box = _access_token_box()
    if not box.get("access"):
        _push_log("✗ Brak logowania GOG — zaloguj się w Ustawieniach.")
        return False

    dlc_ids = {k.split(":")[1] for k in (dlc_keys or [])
               if isinstance(k, str) and k.startswith("dlc:")
               and len(k.split(":")) > 1 and k.split(":")[1]}
    if not dlc_ids:
        _push_log("✗ Nie zaznaczono żadnego DLC.")
        return False

    _push_log("Pobieram build Galaxy dla DLC…")
    try:
        build = _pick_build(pid)
        meta  = _cs_get_zlib(build["link"])
    except Exception as exc:
        _push_log(f"✗ Nie udało się pobrać manifestu builda: {exc}")
        return False

    wanted = {str(l).lower() for l in (langs or _depot_langs_setting())}
    _push_log(f"Języki DLC: {', '.join(sorted(wanted))}")
    hub = _ProgressHub(0)
    ok, inst = _install_dlc_via_depots(meta, dlc_ids, install_dir, pid, box,
                                       hub, get_download_threads(), wanted)
    if inst:
        _apply_support_data(install_dir, pid)
    _send_js({"type": "completion",
              "filename": f"{g['title']} — DLC ({len(inst)})", "speed": "OK"})
    _push_log(f"{'✓' if ok else '⚠'} Dogrywanie DLC zakończone: {len(inst)} zainstalowanych.")
    return ok


def install_dlc(game_id, dlc_keys=None, langs=None) -> dict:
    keys = dlc_keys if isinstance(dlc_keys, list) else []
    langs = langs if isinstance(langs, list) else None
    return _submit_task(lambda: _install_dlc_worker(game_id, keys, langs),
                        _task_label("DLC", game_id), queueable=True)


# ── classic-installer updater (offline installers + extras, no depots) ─────────
# Refreshes the downloaded offline installers + bonus content of a game to GOG's
# current build, then hard-deletes the orphaned old files left behind. Legacy
# entries (old game versions parked in extras, other-OS/other-language builds,
# incremental patches) are intentionally never fetched.

def _update_selection_rows(man: dict, langs: list, include_installers: bool = True) -> list:
    """The 'current, non-legacy' rows the updater manages for a game: ordinary
    (non-heavy) extras always, plus — when `include_installers` is set — Windows
    installers + owned DLC installers in the chosen languages and matching
    language packs. Patches and heavy/legacy entries are deliberately excluded.

    `include_installers=False` is used when the game only ever had its extras
    downloaded (no installer on disk): we refresh just the extras rather than
    pulling a whole installer the user never had."""
    langs = [str(l).lower() for l in (langs or [])]

    def lang_ok(row) -> bool:
        rl = (row.get("lang") or "").lower()
        return (not rl) or (rl in langs)

    rows = []
    if include_installers:
        for r in man.get("installers", []):
            if (r.get("os") or "").lower() == _MY_OS and lang_ok(r):
                rows.append(r)
        for r in man.get("dlcs", []):
            # owned DLC installers only (skip DLC patches and un-owned DLC)
            if (r.get("owned", True) and ":installer:" in (r.get("key") or "")
                    and (r.get("os") or "").lower() == _MY_OS and lang_ok(r)):
                rows.append(r)
        for r in man.get("language_packs", []):
            if lang_ok(r):
                rows.append(r)
    for r in man.get("extras", []):
        if not r.get("heavy"):          # heavy == old-version / legacy pack
            rows.append(r)
    return rows


def _cleanup_orphans(dest_dir: Path, extras_dir: Path, expected: dict) -> list:
    """Hard-delete files under the game's own folders that are NOT part of the
    current (expected) set. Scoped strictly to dest_dir / extras_dir, both of
    which must live under BASE. `expected` maps (dir_str, filename) -> row."""
    removed: list = []
    keep_in: dict = {}
    for (dstr, fname) in expected:
        keep_in.setdefault(dstr, set()).add(fname)

    def under_base(folder: Path) -> bool:
        try:
            folder.resolve().relative_to(BASE.resolve())
            return True
        except ValueError:
            log(f"cleanup: pomijam {folder} (poza BASE)")
            return False

    # Installers / DLC / language packs live in dest_dir with executable-ish exts.
    if dest_dir.exists() and under_base(dest_dir):
        keep = keep_in.get(str(dest_dir), set())
        for pat in INSTALLER_EXTS:
            for f in dest_dir.glob(pat):
                if f.is_file() and f.name not in keep:
                    try:
                        f.unlink()
                        removed.append(str(f))
                    except Exception as exc:
                        log(f"cleanup unlink {f}: {exc}")

    # Extras: only when they have their own subdir is it safe to sweep every file.
    if extras_dir != dest_dir and extras_dir.exists() and under_base(extras_dir):
        keep = keep_in.get(str(extras_dir), set())
        for f in extras_dir.iterdir():
            if f.is_file() and f.name not in keep:
                try:
                    f.unlink()
                    removed.append(str(f))
                except Exception as exc:
                    log(f"cleanup unlink {f}: {exc}")
    return removed


def _update_worker(game_id) -> bool:
    g = next((x for x in scan_games() if x["id"] == str(game_id)), None)
    if not g:
        _push_log("✗ Gra nie znaleziona.")
        return False

    langs = get_settings().get("update_langs") or ["en"]
    # Only refresh the *kinds* of files the game actually has: if it only ever
    # had its extras downloaded (no installer on disk), update just the extras —
    # never pull a whole installer the user never downloaded.
    dl_info = _check_downloaded_for_game(g, scan_downloaded_games())
    has_installer = dl_info.get("has_installer", False)

    man = get_download_manifest(game_id)
    if not man.get("ok"):
        _push_log(f"✗ Nie udało się pobrać manifestu: {man.get('error')}")
        return False
    rows = _update_selection_rows(man, langs, include_installers=has_installer)
    if not rows:
        _push_log(f"✗ Brak pozycji do aktualizacji (języki: {', '.join(langs)}).")
        return False
    if not has_installer:
        _push_log("ℹ Gra ma pobrane tylko extras — aktualizuję wyłącznie extras "
                  "(bez pobierania instalatora).")

    dest_dir   = BASE / g["slug"]
    extras_dir = dest_dir / "extras" if get_settings().get("extras_subdir", True) else dest_dir

    # 1. Resolve every part to GOG's current file and classify it:
    #    • build-tagged installer already on disk ⇒ same build ⇒ skip;
    #    • file WITH a usable GOG checksum ⇒ compare local MD5 vs remote MD5,
    #      re-download only on mismatch;
    #    • file WITHOUT a checksum (most bonus content) ⇒ fetch to RAM and
    #      compare bytes with the on-disk copy, replacing only if different.
    _push_log(f"Sprawdzam aktualne wersje w GOG (języki: {', '.join(langs)})…")
    box = _access_token_box()
    expected: dict = {}     # (dir_str, filename) -> row  (files we should keep)
    to_fetch: list = []     # checksummed files that need a (re)download
    ram_targets: list = []  # (cdn_url, dest, name) — no checksum → RAM compare
    resolve_failed = False

    for row in rows:
        row_dir = extras_dir if row.get("category") == "extra" else dest_dir
        for part in row["parts"]:
            if _cancel.is_set():
                _push_log("⚠ Przerwano.")
                return False
            try:
                info     = _resolve_downlink(part["downlink"], box)
                cdn      = info.get("downlink")
                checksum = info.get("checksum")
                if not cdn:
                    raise RuntimeError("brak downlink")
                fname = _filename_from_url(cdn)
            except Exception as exc:
                _push_log(f"⚠ Nie rozwiązałem linku dla „{row['name']}”: {exc}")
                resolve_failed = True
                continue

            expected[(str(row_dir), fname)] = row
            dest = row_dir / fname

            # Build-tagged installer part already present ⇒ same build ⇒ nothing
            # to do (a new build would carry a different (NNNNN) tag in the name).
            if _BUILD_TAG_RE.search(fname) and dest.exists() and dest.stat().st_size > 0:
                continue

            remote = _remote_md5(checksum) if checksum else None
            if remote:
                same = False
                if dest.exists():
                    try:
                        same = (_md5_path(dest).lower() == remote.lower())
                    except Exception as exc:
                        log(f"update md5 {fname}: {exc}")
                if not same:
                    to_fetch.append({"downlink": part["downlink"],
                                     "size": part.get("size") or 0,
                                     "verify": True, "name": row["name"],
                                     "dest_dir": row_dir, "fresh": True})
            else:
                # GOG has no checksum for this file (e.g. bonus content): the only
                # way to be certain is to fetch it and compare the bytes. Keep the
                # downlink *endpoint* (not the signed CDN url) and re-resolve just
                # before fetching, so long RAM passes never hit an expired link.
                ram_targets.append((part["downlink"], dest, row["name"]))

    # 2. Download the missing / changed files.
    if to_fetch:
        grand = sum(u["size"] for u in to_fetch)
        _push_log(f"Do pobrania (nowe/zmienione): {len(to_fetch)} plik(ów), {_human(grand)}.")
        try:
            free = shutil.disk_usage(str(BASE if BASE.exists() else BASE.anchor)).free
            if grand and free < grand:
                _push_log(f"✗ Za mało miejsca: potrzeba {_human(grand)}, wolne {_human(free)}.")
                return False
        except Exception:
            pass

        conn   = get_download_threads()
        nfiles = len(to_fetch)
        if nfiles >= conn:
            file_workers, segments = conn, 1
        else:
            file_workers = max(1, nfiles)
            segments     = max(1, conn // max(1, nfiles))

        dest_dir.mkdir(parents=True, exist_ok=True)
        extras_dir.mkdir(parents=True, exist_ok=True)

        hub  = _ProgressHub(grand)
        pool = queue.Queue()
        for i in range(1, file_workers + 1):
            pool.put(i)

        results = []
        with ThreadPoolExecutor(max_workers=file_workers) as ex:
            futs = [ex.submit(_download_unit, u, segments, hub, box, pool) for u in to_fetch]
            for fu in as_completed(futs):
                results.append(fu.result())

        if _cancel.is_set():
            _push_log("⚠ Przerwano — sprzątanie POMINIĘTE.")
            return False
        bad = sum(1 for s, _, _ in results if s in ("bad", "err"))
        for s, u, msg in results:
            if s == "err":
                _push_log(f"✗ Błąd przy {u['name']}: {msg}")
        if bad:
            _push_log(f"⚠ {bad} plik(ów) z problemem — sprzątanie starych plików POMINIĘTE "
                      "(nie kasuję, dopóki nowe pliki nie są pewne).")
            return False

    # 2b. No-checksum files: fetch to RAM, compare bytes, replace only if changed.
    #     Certain by content (no size guessing), and identical files never touch
    #     the disk — the download is discarded.
    ram_bad = 0
    if ram_targets and not _cancel.is_set():
        _push_log(f"Weryfikuję {len(ram_targets)} plik(ów) bez sumy GOG "
                  "(pobieram do RAM i porównuję treść)…")
        hub = _ProgressHub(0)
        same_n = repl_n = 0
        for idx, (dl_endpoint, dest, name) in enumerate(ram_targets, 1):
            if _cancel.is_set():
                _push_log("⚠ Przerwano — sprzątanie POMINIĘTE.")
                return False
            try:
                cdn    = _resolve_downlink(dl_endpoint, box).get("downlink")
                if not cdn:
                    raise RuntimeError("brak downlink")
                data   = _fetch_to_ram(cdn, hub, sid=idx, name=dest.name)
                hub.finish(idx, True)
                dl_md5 = _md5_bytes(data)
                identical = (dest.exists()
                             and dest.stat().st_size == len(data)
                             and _md5_path(dest).lower() == dl_md5.lower())
                if identical:
                    same_n += 1                       # discard the download
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    tmp = dest.with_suffix(dest.suffix + ".part")
                    tmp.write_bytes(data)
                    tmp.replace(dest)                 # atomic overwrite
                    repl_n += 1
                    _push_log(f"↻ Zmieniony/nowy: {dest.name} ({_human(len(data))})")
                del data
            except Exception as exc:
                hub.finish(idx, False)
                ram_bad += 1
                _push_log(f"✗ Błąd (RAM) przy {name}: {exc}")
        _push_log(f"Weryfikacja treści: {same_n} bez zmian, {repl_n} zastąpionych/nowych"
                  + (f", {ram_bad} z problemem" if ram_bad else "") + ".")

    if not to_fetch and not ram_targets:
        _push_log("✓ Wszystkie pliki są już w najnowszej wersji.")

    # 3. Orphan cleanup — only when every link resolved and every transfer was OK.
    if ram_bad:
        _push_log("⚠ Część plików bez sumy nie zweryfikowała się — sprzątanie POMINIĘTE.")
        return False
    if resolve_failed:
        _push_log("⚠ Część linków nie rozwiązała się — NIE usuwam starych plików "
                  "(mógłbym skasować coś aktualnego).")
        return False

    removed = _cleanup_orphans(dest_dir, extras_dir, expected)
    if removed:
        _push_log(f"🗑 Usunięto {len(removed)} osieroconych plików (stare wersje):")
        for p in removed:
            _push_log(f"   – {os.path.basename(p)}")
    else:
        _push_log("Brak osieroconych plików do usunięcia.")

    _send_js({"type": "completion", "filename": f"{g['title']} — zaktualizowano", "speed": "OK"})
    _push_log(f"✓ Aktualizacja zakończona: {dest_dir}")
    return True


def update_game(game_id) -> dict:
    return _run_python_task(lambda: _update_worker(game_id), "UPDATE")


def _update_all_worker() -> bool:
    """Update every downloaded game (installers + extras) to GOG's current build,
    one after another, cleaning orphaned old files as it goes."""
    downloaded = scan_downloaded_games()
    targets = [g for g in scan_games()
               if _check_downloaded_for_game(g, downloaded)["downloaded"]]
    if not targets:
        _push_log("Brak pobranych gier do aktualizacji.")
        return True

    _push_log(f"── Aktualizacja wszystkich: {len(targets)} pobranych gier ──")
    done_ok = 0
    failed  = []
    for i, g in enumerate(targets, 1):
        if _cancel.is_set():
            _push_log("⚠ Przerwano — pozostałe gry pominięte.")
            break
        _push_log(f"\n[{i}/{len(targets)}] {g['title']}")
        try:
            ok = _update_worker(g["id"])
        except Exception as exc:
            _push_log(f"✗ Wyjątek przy {g['title']}: {exc}")
            ok = False
        if ok:
            done_ok += 1
        else:
            failed.append(g["title"])

    _push_log(f"\n══ Zakończono: {done_ok}/{len(targets)} OK"
              + (f", problemy: {', '.join(failed)}" if failed else "") + " ══")
    _send_js({"type": "completion",
              "filename": f"Aktualizacja wszystkich — {done_ok}/{len(targets)} OK", "speed": "OK"})
    return not failed


def update_all_games() -> dict:
    return _run_python_task(_update_all_worker, "UPDATE_ALL")


def launch_game(game_id) -> dict:
    """Launch an installed game. Reads the goggame-{id}.info playTasks (as GOG
    Galaxy does) to find the primary executable; falls back to the first .exe in
    the install directory, and finally to just opening the folder."""
    installed = scan_installed_games()
    path = installed.get(str(game_id))
    if not path:
        return {"ok": False, "error": "Gra nie jest zainstalowana"}
    root = Path(path)
    exe = None
    args = ""                       # raw playTask argument string (may be empty)
    workdir = None                  # playTask workingDir, resolved under root
    try:
        info = next(root.glob(f"goggame-{game_id}.info"), None) or next(root.glob("goggame-*.info"), None)
        if info:
            data = json.loads(info.read_text(encoding="utf-8", errors="replace"))
            tasks = data.get("playTasks") or []
            prim = next((t for t in tasks if t.get("isPrimary") and t.get("path")), None) \
                   or next((t for t in tasks if t.get("category") == "game" and t.get("path")), None) \
                   or next((t for t in tasks if t.get("path")), None)
            if prim and prim.get("path"):
                cand = (root / prim["path"].replace("\\", "/"))
                if cand.exists():
                    exe = cand
                    args = prim.get("arguments") or ""
                    wd = prim.get("workingDir")
                    if wd:
                        workdir = root / wd.replace("\\", "/")
    except Exception as exc:
        log(f"launch_game info parse: {exc}")
    if exe is None:
        exes = sorted(root.rglob("*.exe"))
        # Skip obvious non-game binaries (incl. the bundled DOSBox config tool).
        exe = next((e for e in exes if not re.search(
            r"(unins|redist|vcredist|dxsetup|dotnet|crashpad|setup|gogdosconfig|dosbox)",
            e.name, re.I)), exes[0] if exes else None)
    if exe is None:
        return open_folder(str(root))
    if workdir is None or not Path(workdir).is_dir():
        workdir = exe.parent
    try:
        # DOS/ScummVM games need their -conf arguments; os.startfile can't pass
        # any, so build the command line ourselves.  A string command lets
        # Windows CreateProcess parse the (backslash-heavy, quoted) args as-is.
        cmd = f'"{exe}" {args}'.strip() if args else f'"{exe}"'
        subprocess.Popen(cmd, cwd=str(workdir))
        _push_log(f"▶ Uruchomiono grę: {exe.name}")
        return {"ok": True, "exe": str(exe)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def run_installer(game_id) -> dict:
    """Launch the already-downloaded offline installer (setup*.exe)."""
    g = next((x for x in scan_games() if x["id"] == str(game_id)), None)
    if not g:
        return {"ok": False, "error": "Gra nie znaleziona"}
    dl = _check_downloaded_for_game(g, scan_downloaded_games())
    if not dl["downloaded"]:
        return {"ok": False, "error": "Installer nie jest pobrany"}
    folder = Path(dl["installer_path"])
    exes = sorted(folder.glob("*.exe"))
    exe  = next((e for e in exes if e.name.lower().startswith("setup")), exes[0] if exes else None)
    if not exe:
        return {"ok": False, "error": "Nie znaleziono pliku .exe w katalogu instalatora"}
    try:
        os.startfile(str(exe))          # detached, interactive Inno Setup
        _push_log(f"▶ Uruchomiono instalator: {exe.name}")
        return {"ok": True, "exe": str(exe)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


_HERO_ART_CACHE: dict = {}

# ── SteamGridDB (hero + logo art — GOG's own artwork is often low quality) ────
# Ported from the PyLinks IconManager approach: Bearer auth, autocomplete search
# with query-shortening fallback for rare/old titles, bigram name similarity to
# pick the best match, then heroes/logos endpoints for the actual art.
SGDB_BASE = "https://www.steamgriddb.com/api/v2"
_SGDB_CACHE: dict = {}          # pid -> {"hero":url, "logo":url, "sgdb_id":id}


def _sgdb_key() -> str:
    return _get_secret("sgdb_key")


def _sgdb_get(url: str) -> dict | None:
    key = _sgdb_key()
    if not key:
        return None
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0", "Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req, timeout=12) as r:
            obj = json.loads(r.read().decode("utf-8", "replace"))
        return obj if obj.get("success") else None
    except Exception as exc:
        log(f"[SGDB] {url} :: {exc}")
        return None


def _name_similarity(a: str, b: str) -> float:
    def bigrams(s: str) -> set:
        s = re.sub(r"[^a-z0-9 ]", "", s.lower())
        return set(s[i:i + 2] for i in range(len(s) - 1))
    ba, bb = bigrams(a), bigrams(b)
    if not ba and not bb:
        return 1.0
    if not ba or not bb:
        return 0.0
    return 2 * len(ba & bb) / (len(ba) + len(bb))


def _sgdb_search(query: str, max_results: int = 8) -> list:
    enc = urllib.request.quote(query)
    obj = _sgdb_get(f"{SGDB_BASE}/search/autocomplete/{enc}")
    return (obj.get("data") or [])[:max_results] if obj else []


def _sgdb_search_with_fallback(query: str) -> list:
    """Autocomplete doesn't index every title — old/rare games often only match on
    a shortened query. Try the full title, then progressively shorter variants."""
    res = _sgdb_search(query)
    if res:
        return res
    seen, attempts = {query}, []
    if " - " in query:
        attempts.append(query.split(" - ")[0].strip())
    for sep in (": ", ":"):
        if sep in query:
            attempts.append(query.split(sep)[0].strip()); break
    words = query.split()
    if len(words) >= 3:
        attempts.append(" ".join(words[:2]).rstrip(":;,- "))
    if len(words) >= 2 and len(words[0].rstrip(":;,- ")) >= 4:
        attempts.append(words[0].rstrip(":;,- "))
    for a in attempts:
        if not a or a in seen:
            continue
        seen.add(a)
        res = _sgdb_search(a)
        if res:
            return res
    return []


def _sgdb_match_id(title: str) -> int | None:
    """Return the best-matching SGDB game id for a title, or None."""
    results = _sgdb_search_with_fallback(title)
    if not results:
        return None
    best, best_score = None, -1.0
    for r in results:
        sim = _name_similarity(title, r.get("name", ""))
        if sim > best_score:
            best, best_score = r, sim
    # Accept only reasonably close matches to avoid grabbing art for a wrong game.
    if best and best_score >= 0.45:
        return best.get("id")
    return results[0].get("id")     # fall back to autocomplete's top hit


def _sgdb_best_asset(kind: str, sgdb_id) -> str:
    lst = _sgdb_asset_list(kind, sgdb_id)
    return lst[0]["url"] if lst else ""


def _sgdb_asset_list(kind: str, sgdb_id) -> list:
    """All heroes/logos/grids for an SGDB id, best first, as [{url, thumb}]."""
    params = "?types=static,animated" if kind in ("heroes", "grids") else ""
    obj = _sgdb_get(f"{SGDB_BASE}/{kind}/game/{sgdb_id}{params}")
    data = (obj.get("data") or []) if obj else []
    def rank(a):
        return (a.get("score") or 0, 1 if a.get("style") == "official" else 0)
    data.sort(key=rank, reverse=True)
    out = []
    for a in data:
        url = a.get("url")
        if url:
            out.append({"url": url, "thumb": a.get("thumb") or url})
    return out


def _sgdb_art(title: str, pid: str, override_id=None) -> dict:
    """Resolve hero + logo for a game via SGDB, cached per product id. If
    `override_id` is given (a manually-set SGDB game id), use it directly instead
    of searching by title — this fixes wrong matches (e.g. old GOG version vs. the
    newest game SGDB indexes)."""
    ck = f"{pid}:{override_id or ''}"
    if ck in _SGDB_CACHE:
        return _SGDB_CACHE[ck]
    out = {"hero": "", "logo": "", "sgdb_id": None}
    sid = override_id or _sgdb_match_id(title)
    if sid:
        out["sgdb_id"] = sid
        out["hero"] = _sgdb_best_asset("heroes", sid)
        out["logo"] = _sgdb_best_asset("logos", sid)
    _SGDB_CACHE[ck] = out
    return out


def _resolve_gog_template(href: str) -> str:
    """v2 image hrefs are templated, e.g. .../<hash>.{ext} or .../<hash>{formatter}.{ext}.
    Drop the formatter (→ original size) and pick a concrete extension."""
    if not href:
        return ""
    href = href.replace("{formatter}", "").replace("{ext}", "jpg")
    if href.startswith("//"):
        href = "https:" + href
    return href


def sgdb_test() -> dict:
    """Verify the configured SteamGridDB key by hitting a cheap endpoint."""
    if not _sgdb_key():
        return {"ok": False, "error": "Brak klucza SGDB"}
    obj = _sgdb_get(f"{SGDB_BASE}/search/autocomplete/celeste")
    if obj is not None:
        return {"ok": True, "count": len(obj.get("data") or [])}
    return {"ok": False, "error": "Klucz odrzucony lub brak połączenia"}


# ── per-game art store: {pid: {"hero": {url,source,pinned}, "logo": {...}}} ────
# The Settings source (GOG/SGDB) is only the DEFAULT. Actual art is resolved per
# game: a pinned choice wins; otherwise it's resolved from the default and the
# result is cached here so later reads are instant and stable across sessions.
_ART: dict | None = None
_ART_LOCK = threading.Lock()


def _art_load() -> dict:
    global _ART
    if _ART is not None:
        return _ART
    with _ART_LOCK:
        if _ART is None:
            data = {}
            if ART_FILE.exists():
                try:
                    data = json.loads(ART_FILE.read_text(encoding="utf-8"))
                except Exception as exc:
                    log(f"art.json read failed: {exc}")
            _ART = data if isinstance(data, dict) else {}
        return _ART


def _art_save() -> None:
    try:
        CACHE.mkdir(parents=True, exist_ok=True)
        _atomic_write(ART_FILE, json.dumps(_ART or {}, ensure_ascii=False).encode("utf-8"))
    except Exception as exc:
        log(f"art.json write failed: {exc}")


def _art_get(pid: str) -> dict:
    return _art_load().get(str(pid)) or {}


def _art_set_asset(pid, asset, url, source, pinned) -> None:
    art = _art_load()
    with _ART_LOCK:
        rec = art.get(str(pid)) or {}
        rec[asset] = {"url": url or "", "source": source, "pinned": bool(pinned)}
        art[str(pid)] = rec
        _art_save()


def _art_clear(pid, asset=None) -> None:
    art = _art_load()
    with _ART_LOCK:
        rec = art.get(str(pid))
        if not rec:
            return
        if asset:
            rec.pop(asset, None)
            if not rec:
                art.pop(str(pid), None)
        else:
            art.pop(str(pid), None)
        _art_save()


def _gog_art(pid: str, product: dict) -> dict:
    """GOG's own hero (Galaxy background) + logo (v2 API, else product JSON)."""
    out = {"hero": "", "logo": ""}
    imgs = (product or {}).get("images") or {}
    out["logo"] = norm_url(imgs.get("logo")) or ""
    try:
        with urllib.request.urlopen(
            urllib.request.Request(GOG_V2_GAMES_API.format(id=pid),
                                   headers={"User-Agent": "Mozilla/5.0"}), timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        links = data.get("_links") or {}
        for field in ("galaxyBackgroundImage", "backgroundImage", "boxArtImage"):
            v = links.get(field) or {}
            href = v.get("href") if isinstance(v, dict) else v
            if href:
                out["hero"] = _resolve_gog_template(str(href)); break
        v = links.get("logo") or {}
        href = v.get("href") if isinstance(v, dict) else v
        if href:
            out["logo"] = _resolve_gog_template(str(href))
    except Exception as exc:
        log(f"v2 games fetch {pid} :: {exc}")
    return out


def get_hero_art(game_id) -> dict:
    """Resolve a game's hero + logo PER GAME. A pinned choice (picked by the user)
    always wins. Otherwise the asset is resolved from the Settings default source
    and the result is cached (auto) so later reads are instant and stable. Changing
    the Settings source re-resolves only the auto assets, never the pinned ones."""
    g = next((x for x in scan_games() if x["id"] == str(game_id)), None)
    if not g:
        return {"ok": False, "error": "Gra nie znaleziona"}
    pid = str(g["product"].get("id") or "").strip()
    if not pid:
        return {"ok": False, "error": "brak product_id"}

    st = get_settings()
    hero_def = (st.get("art_hero_source") or "gog").lower()
    logo_def = (st.get("art_logo_source") or "sgdb").lower()
    override = g.get("sgdb_id")
    rec = _art_get(pid)

    def cached(asset, default_src):
        c = rec.get(asset)
        if c and c.get("pinned"):
            return c.get("url", ""), c.get("source", default_src), True      # user's pick
        if c and c.get("source") == default_src:
            return c.get("url", ""), default_src, True                        # auto still valid
        return "", default_src, False

    hero_url, hero_src, hero_ok = cached("hero", hero_def)
    logo_url, logo_src, logo_ok = cached("logo", logo_def)

    # Fetch only the sources we still need to resolve.
    need = set()
    if not hero_ok: need.add(hero_src)
    if not logo_ok: need.add(logo_src)
    sg = {"hero": "", "logo": ""}
    if "sgdb" in need and _sgdb_key():
        try:
            a = _sgdb_art(g.get("title") or g.get("slug") or "", pid, override_id=override)
            sg = {"hero": a.get("hero", ""), "logo": a.get("logo", "")}
        except Exception as exc:
            log(f"[SGDB] art {pid} :: {exc}")
    gog = _gog_art(pid, g.get("product")) if "gog" in need else {"hero": "", "logo": ""}
    src = {"gog": gog, "sgdb": sg}

    # Persist newly auto-resolved assets so next time it's a cache hit.
    if not hero_ok:
        hero_url = src[hero_src]["hero"]
        _art_set_asset(pid, "hero", hero_url, hero_src, pinned=False)
    if not logo_ok:
        logo_url = src[logo_src]["logo"]
        _art_set_asset(pid, "logo", logo_url, logo_src, pinned=False)

    return {"ok": True, "url": hero_url, "logo": logo_url,
            "hero_source": hero_src, "logo_source": logo_src,
            "hero_pinned": bool(rec.get("hero", {}).get("pinned")),
            "logo_pinned": bool(rec.get("logo", {}).get("pinned")),
            "sgdb_id": override or None}


def clear_hero_cache() -> dict:
    """Wipe in-memory fetch caches (auto art re-resolves from the current default;
    pinned per-game choices are untouched)."""
    _HERO_ART_CACHE.clear()
    _SGDB_CACHE.clear()
    return {"ok": True}


def refresh_hero_art(game_id) -> dict:
    """Re-resolve a game's art: drop AUTO (non-pinned) choices + fetch caches so
    they resolve fresh; PINNED choices are kept."""
    g = next((x for x in scan_games() if x["id"] == str(game_id)), None)
    if g:
        pid = str(g["product"].get("id") or "").strip()
        for k in [k for k in _SGDB_CACHE if k.split(":")[0] == pid]:
            _SGDB_CACHE.pop(k, None)
        rec = _art_get(pid)
        for asset in ("hero", "logo"):
            if rec.get(asset) and not rec[asset].get("pinned"):
                _art_clear(pid, asset)
    return get_hero_art(game_id)


def get_art_options(game_id) -> dict:
    """List every hero/logo the user can pick — from SteamGridDB (all variants) and
    GOG — so they can choose specific artwork per game. Network call; only invoked
    when the picker is opened."""
    g = next((x for x in scan_games() if x["id"] == str(game_id)), None)
    if not g:
        return {"ok": False, "error": "Gra nie znaleziona"}
    pid = str(g["product"].get("id") or "").strip()
    override = g.get("sgdb_id")
    heroes, logos = [], []

    # GOG
    gog = _gog_art(pid, g.get("product"))
    if gog["hero"]:
        heroes.append({"url": gog["hero"], "thumb": gog["hero"], "source": "gog"})
    if gog["logo"]:
        logos.append({"url": gog["logo"], "thumb": gog["logo"], "source": "gog"})

    # SGDB (all variants). When manually editing, if the proper hero/logo art is
    # missing, fall back to other SGDB asset types so there's still something to
    # pick: grids (covers) can serve as a hero, icons as a logo.
    sid = None
    if _sgdb_key():
        try:
            sid = override or _sgdb_match_id(g.get("title") or g.get("slug") or "")
            if sid:
                sg_heroes = _sgdb_asset_list("heroes", sid)
                for h in sg_heroes:
                    heroes.append({"url": h["url"], "thumb": h["thumb"], "source": "sgdb"})
                if not sg_heroes:
                    for gd in _sgdb_asset_list("grids", sid):
                        heroes.append({"url": gd["url"], "thumb": gd["thumb"], "source": "sgdb"})
                sg_logos = _sgdb_asset_list("logos", sid)
                for lo in sg_logos:
                    logos.append({"url": lo["url"], "thumb": lo["thumb"], "source": "sgdb"})
                if not sg_logos:
                    for ic in _sgdb_asset_list("icons", sid):
                        logos.append({"url": ic["url"], "thumb": ic["thumb"], "source": "sgdb"})
        except Exception as exc:
            log(f"[SGDB] options {pid} :: {exc}")

    rec = _art_get(pid)
    return {"ok": True, "sgdb_id": sid or override, "heroes": heroes, "logos": logos,
            "current": {
                "hero": rec.get("hero") or None,
                "logo": rec.get("logo") or None,
            }}


def set_art_asset(game_id, asset, url, source) -> dict:
    """Pin a specific hero or logo (saved to the per-game art cache)."""
    if asset not in ("hero", "logo"):
        return {"ok": False, "error": "asset musi być 'hero' lub 'logo'"}
    g = next((x for x in scan_games() if x["id"] == str(game_id)), None)
    if not g:
        return {"ok": False, "error": "Gra nie znaleziona"}
    pid = str(g["product"].get("id") or "").strip()
    _art_set_asset(pid, asset, url, (source or "sgdb"), pinned=True)
    _SGDB_CACHE.clear()
    return refresh_and_get(game_id)


def clear_art_asset(game_id, asset=None) -> dict:
    """Un-pin a hero/logo (or both) → back to the Settings default (auto)."""
    g = next((x for x in scan_games() if x["id"] == str(game_id)), None)
    if not g:
        return {"ok": False, "error": "Gra nie znaleziona"}
    pid = str(g["product"].get("id") or "").strip()
    _art_clear(pid, asset if asset in ("hero", "logo") else None)
    return refresh_hero_art(game_id)


def refresh_and_get(game_id) -> dict:
    """get_hero_art but without dropping pinned/auto — just returns current state."""
    return get_hero_art(game_id)


def _parse_sgdb_id(raw) -> int | None:
    """Accept a bare SGDB game id or a steamgriddb.com/game/NNNN URL."""
    s = str(raw or "").strip()
    m = re.search(r"/game/(\d+)", s)
    if m:
        return int(m.group(1))
    return int(s) if s.isdigit() else None


def _lib_set_sgdb(game_id, sid) -> bool:
    lib = _lib_load()
    with _LIB_LOCK:
        for entry in lib.values():
            if str((entry.get("product") or {}).get("id")) == str(game_id):
                if sid:
                    entry["sgdb_id"] = sid
                else:
                    entry.pop("sgdb_id", None)
                _lib_save(lib)
                return True
    return False


def set_sgdb_override(game_id, id_or_url) -> dict:
    """Pin a specific SteamGridDB game id for this game (fixes wrong auto-matches,
    e.g. an old GOG version getting the newest game's art)."""
    sid = _parse_sgdb_id(id_or_url)
    if not sid:
        return {"ok": False, "error": "Podaj SGDB ID lub adres .../game/NNNN"}
    if not _lib_set_sgdb(game_id, sid):
        return {"ok": False, "error": "Gra nie znaleziona"}
    clear_hero_cache()
    art = refresh_hero_art(game_id)
    return {"ok": True, "sgdb_id": sid, **({} if not isinstance(art, dict) else art)}


def clear_sgdb_override(game_id) -> dict:
    if not _lib_set_sgdb(game_id, None):
        return {"ok": False, "error": "Gra nie znaleziona"}
    clear_hero_cache()
    art = refresh_hero_art(game_id)
    return {"ok": True, "sgdb_id": None, **({} if not isinstance(art, dict) else art)}


def get_sgdb_override(game_id) -> dict:
    g = next((x for x in scan_games() if x["id"] == str(game_id)), None)
    return {"ok": True, "sgdb_id": (g or {}).get("sgdb_id")}


def _task_label(prefix: str, game_id) -> str:
    g = next((x for x in scan_games() if x["id"] == str(game_id)), None)
    return f"{prefix}: {g['title']}" if g else f"{prefix}: {game_id}"


def start_download(game_id, selection_keys) -> dict:
    keys = selection_keys if isinstance(selection_keys, list) else []
    return _submit_task(lambda: _download_worker(game_id, keys),
                        _task_label("Pobieranie", game_id), queueable=True)


def _folder_dialog():
    """Open a folder picker using the current pywebview API (FileDialog.FOLDER),
    falling back to the deprecated FOLDER_DIALOG constant on older versions."""
    kind = getattr(getattr(webview, "FileDialog", None), "FOLDER", None) \
           or getattr(webview, "FOLDER_DIALOG", None)
    return webview.windows[0].create_file_dialog(kind, allow_multiple=False)


def choose_json_dir() -> dict:
    dirs = _folder_dialog()
    if dirs:
        global JSON_DIR
        JSON_DIR = Path(dirs[0])
        ensure_dirs()
        _persist_dir("json_dir", str(JSON_DIR))
        return {"ok": True, "json_dir": str(JSON_DIR)}
    return {"ok": False, "error": "Anulowano"}


def choose_install_dir(new_dir=None) -> dict:
    global BASE
    if not new_dir:
        dirs = _folder_dialog()
        if dirs:
            new_dir = dirs[0]
        else:
            return {"ok": False, "error": "Anulowano"}
    BASE = Path(new_dir)
    BASE.mkdir(parents=True, exist_ok=True)
    _persist_dir("install_dir", str(BASE))
    return {"ok": True, "install_dir": str(BASE)}


def choose_games_dir(new_dir=None) -> dict:
    global GOG_GAMES
    if not new_dir:
        dirs = _folder_dialog()
        if dirs:
            new_dir = dirs[0]
        else:
            return {"ok": False, "error": "Anulowano"}
    GOG_GAMES = Path(new_dir)
    _persist_dir("games_dir", str(GOG_GAMES))
    return {"ok": True, "games_dir": str(GOG_GAMES)}


def launch_download(game_id) -> dict:
    """Legacy entry point — now routes to the native downloader with the
    manifest's default selection (my platform + EN installer, light extras)."""
    man = get_download_manifest(game_id)
    if not man.get("ok"):
        return man
    keys = [r["key"]
            for sec in ("installers", "patches", "language_packs", "extras")
            for r in man.get(sec, []) if r.get("default")]
    if not keys:
        return {"ok": False, "error": "Brak domyślnych plików do pobrania."}
    return start_download(game_id, keys)


def delete_installer(game_id) -> dict:
    g = next((x for x in scan_games() if x["id"] == str(game_id)), None)
    if not g:
        return {"ok": False, "error": "Gra nie znaleziona"}
    dl = _check_downloaded_for_game(g, scan_downloaded_games())
    if not dl["downloaded"]:
        return {"ok": False, "error": "Brak plików instalatora"}
    game_dir = Path(dl["installer_path"])
    # Safety: the directory must be directly inside BASE
    try:
        game_dir.resolve().relative_to(BASE.resolve())
    except ValueError:
        return {"ok": False, "error": "Ścieżka poza katalogiem GOGinstall – operacja zablokowana"}
    try:
        shutil.rmtree(str(game_dir))
        return {"ok": True, "deleted_path": str(game_dir), "files": dl["installer_files"]}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def delete_installed_game(game_id) -> dict:
    """Remove an installed game's directory from GOG_GAMES and let the next scan
    pick up the change (no app restart needed)."""
    installed = scan_installed_games()
    path = installed.get(str(game_id))
    if not path:
        return {"ok": False, "error": "Gra nie jest zainstalowana"}
    game_dir = Path(path)
    # Safety: the target must be a *direct* child of GOG_GAMES — never the root
    # itself, a nested subfolder, or anything outside the games directory.
    try:
        if game_dir.resolve().parent != GOG_GAMES.resolve():
            return {"ok": False,
                    "error": "Ścieżka poza katalogiem GOG Games – operacja zablokowana"}
    except Exception as exc:
        return {"ok": False, "error": f"Nie można zweryfikować ścieżki: {exc}"}
    try:
        shutil.rmtree(str(game_dir))
        return {"ok": True, "deleted_path": str(game_dir)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def open_folder(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {"ok": False, "error": f"Folder nie istnieje: {path}"}
    try:
        os.startfile(str(p))
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def kill_command() -> dict:
    _cancel.set()
    # Stop means stop: drop everything still queued so the pipeline doesn't
    # auto-continue after the current job is aborted.
    with _proc_lock:
        _task_queue.clear()
    _emit_queue()
    with _proc_lock:
        proc = _current_proc
    if proc:
        try:
            proc.kill()
            _push_terminal("\n⚠ Proces przerwany przez użytkownika.")
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
    _push_log("⚠ Anulowano.")
    return {"ok": True}


# ── pywebview API class ────────────────────────────────────────────────────────
class Api:
    def build_index(self):                      return build_index()
    def get_games(self):                        return get_games()
    def sync_json_all(self):                    return sync_json_all()
    def sync_json_game(self, game_id):          return sync_json_game(game_id)
    def choose_json_dir(self):                  return choose_json_dir()
    def choose_install_dir(self, new_dir=None): return choose_install_dir(new_dir)
    def choose_games_dir(self, new_dir=None):   return choose_games_dir(new_dir)
    def launch_download(self, game_id):         return launch_download(game_id)
    def get_downloads(self, game_id):           return get_downloads(game_id)
    def get_hero_art(self, game_id):            return get_hero_art(game_id)
    def get_game_extras(self, game_id):         return get_game_extras(game_id)
    def start_download(self, game_id, keys):    return start_download(game_id, keys)
    def install_game(self, game_id, keys=None, langs=None): return install_game(game_id, keys, langs)
    def install_dlc(self, game_id, keys=None, langs=None):   return install_dlc(game_id, keys, langs)
    def get_build_languages(self, game_id):     return get_build_languages(game_id)
    def update_game(self, game_id):             return update_game(game_id)
    def update_all_games(self):                 return update_all_games()
    def run_installer(self, game_id):           return run_installer(game_id)
    def launch_game(self, game_id):             return launch_game(game_id)
    def refresh_hero_art(self, game_id):        return refresh_hero_art(game_id)
    def clear_hero_cache(self):                 return clear_hero_cache()
    def set_sgdb_override(self, game_id, v):    return set_sgdb_override(game_id, v)
    def clear_sgdb_override(self, game_id):     return clear_sgdb_override(game_id)
    def get_sgdb_override(self, game_id):       return get_sgdb_override(game_id)
    def get_art_options(self, game_id):         return get_art_options(game_id)
    def set_art_asset(self, game_id, a, u, s2): return set_art_asset(game_id, a, u, s2)
    def clear_art_asset(self, game_id, a=None): return clear_art_asset(game_id, a)
    def sgdb_test(self):                        return sgdb_test()
    def security_status(self):                  return security_status()
    def gog_login_start(self):                  return gog_login_start()
    def gog_login_finish(self, pasted):         return gog_login_finish(pasted)
    def gog_login_status(self):                 return gog_login_status()
    def get_onboarding_state(self):             return get_onboarding_state()
    def mark_onboarded(self):                   return mark_onboarded()
    def delete_installer(self, game_id):        return delete_installer(game_id)
    def delete_installed_game(self, game_id):   return delete_installed_game(game_id)
    def open_folder(self, path):                return open_folder(path)
    def kill_command(self):                     return kill_command()
    def refresh_ratings(self):                  return refresh_ratings()
    def refresh_purchase_dates(self):           return refresh_purchase_dates()
    def get_queue(self):                        return get_queue()
    def cancel_queued(self, item_id):           return cancel_queued(item_id)
    def clear_queue(self):                      return clear_queue()
    def get_settings(self):                     return get_settings()
    def save_settings(self, settings):          return save_settings(settings)


if __name__ == "__main__":
    _FROZEN = getattr(sys, "frozen", False)
    # Keep the log file from growing without bound across runs.
    try:
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > 2_000_000:
            LOG_FILE.unlink()
    except Exception:
        pass
    log(f"=== start (frozen={_FROZEN}) app_dir={APP_DIR} html={HTML} ===")
    if not HTML.exists():
        log(f"FATAL: nie znaleziono {HTML}")
    _apply_dir_settings()
    ensure_dirs()
    build_index()
    webview.create_window(
        f"GOG Library Manager v{APP_VERSION}", str(HTML),
        js_api=Api(), width=1600, height=1000,
    )
    # debug (devtools) only during development; off in the packaged exe.
    webview.start(http_server=True, debug=not _FROZEN)
