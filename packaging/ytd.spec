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
version_file = None
if sys.platform == "win32":
    # File properties (Details tab) name the publisher; an exe with no version
    # info and no signature looks far more suspicious to SmartScreen/Defender.
    import tempfile
    parts = [int(x) for x in VERSION.split(".")[:3]]
    nums = tuple(parts + [0] * (4 - len(parts)))
    strings = {
        "CompanyName": "Garv", "FileDescription": NAME, "FileVersion": VERSION, "InternalName": NAME,
        "LegalCopyright": "Developed by Garv", "OriginalFilename": NAME + ".exe",
        "ProductName": NAME, "ProductVersion": VERSION,
    }
    rows = ",\n          ".join(f"StringStruct({k!r}, {v!r})" for k, v in strings.items())
    # PyInstaller's documented version-file format (evaluated by PyInstaller, not imported here).
    version_file = str(Path(tempfile.mkdtemp()) / "version_info.txt")
    Path(version_file).write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={nums}, prodvers={nums}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
          {rows}])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])]),
  ],
)
""", "utf-8")

pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name=NAME,
    console=False,
    upx=False,
    icon=str(ROOT / "packaging" / ("icon.icns" if IS_MAC else "icon.ico")),
    version=version_file,
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
            "NSHumanReadableCopyright": "Developed by Garv",
        },
    )
