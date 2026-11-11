# -*- mode: python ; coding: utf-8 -*-
# Gera dist/G500Config.exe (um único arquivo, sem precisar de Python no outro PC).
# Uso:  .venv\Scripts\pyinstaller G500Config.spec --noconfirm
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas, binaries, hiddenimports = [("assets", "assets"), ("g500/webui", "g500/webui")], [], []
for pkg in ("bleak", "sv_ttk", "sdl2dll", "vgamepad", "webview", "clr_loader", "pythonnet"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h
hiddenimports += collect_submodules("winrt")
hiddenimports += collect_submodules("sdl2")
hiddenimports += ["g500.webapp", "g500.overlay", "g500.controller", "g500.gui", "clr"]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["usb", "libusb_package", "hid", "PIL", "numpy"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="G500Config",
    icon="assets/icone.ico",
    version="version_info.txt",
    console=False,
    upx=False,
    runtime_tmpdir=None,
)
