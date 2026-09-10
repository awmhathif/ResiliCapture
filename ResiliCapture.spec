# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

project = Path(SPECPATH)
binaries = []
for name in ("ffmpeg.exe", "ffprobe.exe"):
    candidate = project / "bin" / name
    if candidate.exists():
        binaries.append((str(candidate), "bin"))

a = Analysis(
    [str(project / "app.py")],
    pathex=[str(project)],
    binaries=binaries,
    datas=[(str(project / "assets"), "assets")],
    hiddenimports=["PIL.ImageGrab", "pynput.keyboard._win32", "pynput.mouse._win32", *collect_submodules("pystray")],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ResiliCapture",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(project / "assets" / "app.ico"),
    version=str(project / "version_info.txt"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ResiliCapture",
)
