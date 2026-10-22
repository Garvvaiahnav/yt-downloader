# PyInstaller spec for the installed app. Build with packaging/build_mac.sh or
# packaging/build_windows.ps1, which fetch the bundled binaries first.
import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).parent
IS_MAC = sys.platform == "darwin"
NAME = "Video Downloader"
VERSION = re.search(r'"(.+)"', (ROOT / "ytd" / "__init__.py").read_text()).group(1)

exe_suffix = ".exe" if sys.platform == "win32" else ""
binaries = [(str(ROOT / "packaging" / "bin" / (n + exe_suffix)), "bin") for n in ("ffmpeg", "ffprobe", "deno")]
for src, _ in binaries:
    if not Path(src).is_file():
        raise SystemExit(f"Missing {src}. Run packaging/fetch_bins.py first.")

datas = [(str(ROOT / "web"), "web")]
datas += collect_data_files("yt_dlp_ejs") + collect_data_files("certifi") + collect_data_files("webview")
# updater.py compares the bundled versions against downloaded updates.
datas += copy_metadata("yt-dlp") + copy_metadata("yt-dlp-ejs")

a = Analysis(
    [str(ROOT / "desktop.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=collect_submodules("yt_dlp") + collect_submodules("uvicorn") + collect_submodules("ytd"),
    excludes=["tkinter", "PyQt5", "PyQt6", "PySide2", "PySide6", "qtpy", "gi", "IPython", "matplotlib", "numpy"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name=NAME,
    console=False,
    upx=False,
    icon=str(ROOT / "packaging" / ("icon.icns" if IS_MAC else "icon.ico")),
)
coll = COLLECT(exe, a.binaries, a.datas, name=NAME, upx=False)

if IS_MAC:
    app = BUNDLE(
        coll,
        name=f"{NAME}.app",
        icon=str(ROOT / "packaging" / "icon.icns"),
        bundle_identifier="com.masterhooks.ytdownloader",
        info_plist={
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "LSMinimumSystemVersion": "11.0",
            "NSHighResolutionCapable": True,
            "NSHumanReadableCopyright": "Made by Garv",
        },
    )
