# PyInstaller spec for the command-line Windows executable.
from pathlib import Path

project_root = Path(SPECPATH).resolve().parents[1]
templates = project_root / "diskvis" / "templates"

a = Analysis(
    [str(project_root / "packaging" / "windows" / "cli_entry.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[(str(templates), "diskvis/templates")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="diskvis",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    version=str(project_root / "packaging" / "windows" / "version_info.txt"),
)
