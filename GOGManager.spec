# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for GOG Library Manager.
# Build:  pyinstaller GOGManager.spec --noconfirm
#
# Layout expected next to this .spec:
#   app.py
#   assets/index.html
#
# Requires (pip):  pywebview  pythonnet  cryptography  zstandard
# (On Python 3.14 `zstandard` is optional — the stdlib `compression.zstd` is used.)
# The target PC needs the Microsoft Edge WebView2 runtime (built into Windows 11).

from PyInstaller.utils.hooks import collect_all, collect_submodules

datas, binaries, hiddenimports = [], [], []

# The single-file UI must be bundled and is loaded from RESOURCE_DIR/assets.
datas += [('assets/index.html', 'assets')]

# pywebview: platform backends + its bundled JS/DLLs. http_server=True pulls in
# bottle; the Windows backend pulls in pythonnet (clr).
for pkg in ('webview', 'cryptography'):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

hiddenimports += [
    'webview.platforms.winforms',
    'webview.platforms.edgechromium',
    'webview.platforms.cef',
    'bottle',
    'proxy_tools',
    'clr',                       # pythonnet (Windows WebView2/WinForms backend)
    'compression.zstd',         # Python 3.14 stdlib zstd (imported dynamically)
    'zstandard',                # 3rd-party zstd fallback (if installed)
]
# pythonnet is optional at analysis time; collect it if present.
try:
    d, b, h = collect_all('pythonnet')
    datas += d; binaries += b; hiddenimports += h
    hiddenimports += collect_submodules('clr_loader')
except Exception:
    pass

block_cipher = None

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter'],       # not used; trims size
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='GOGManager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,              # GUI app (no console window)
    disable_windowed_traceback=False,
    icon=None,                  # set to 'assets/app.ico' if you add one
)
