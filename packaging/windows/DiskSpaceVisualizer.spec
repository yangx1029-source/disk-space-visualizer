# PyInstaller spec for the double-clickable Windows GUI.
from pathlib import Path

project_root = Path(SPECPATH).resolve().parents[1]
templates = project_root / "diskvis" / "templates"
dashboard_templates = project_root / "diskvis" / "dashboard" / "templates"

a = Analysis(
    [str(project_root / "diskvis" / "gui.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        (str(templates), "diskvis/templates"),
        (str(dashboard_templates), "diskvis/dashboard/templates"),
    ],
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
    name="DiskSpaceVisualizer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    version=str(project_root / "packaging" / "windows" / "version_info.txt"),
)
