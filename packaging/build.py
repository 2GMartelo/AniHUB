"""Builds the Windows installer:  .venv\Scripts\python packaging\build.py

1. renders the app icon to build/anihub.ico
2. PyInstaller (one folder, no console) -> dist/AniHUB/
3. Inno Setup -> dist/AniHUB-Setup-<version>.exe
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

EXCLUDES = ["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick", "PySide6.Qt3DCore",
            "PySide6.Qt3DRender", "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtCharts", "PySide6.QtDataVisualization",
            "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtDesigner", "PySide6.QtSql", "PySide6.QtTest",
            "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtSensors", "PySide6.QtSerialPort", "tkinter", "pytest"]


def make_icon() -> Path:
    from PySide6.QtGui import QGuiApplication

    from anihub.ui.theme import make_app_icon

    app = QGuiApplication.instance() or QGuiApplication([])
    out = ROOT / "build" / "anihub.ico"
    out.parent.mkdir(exist_ok=True)
    make_app_icon().pixmap(256, 256).save(str(out), "ICO")
    assert out.exists() and out.stat().st_size > 0, "icon was not written"
    return out


def find_iscc() -> str | None:
    found = shutil.which("ISCC")
    if found:
        return found
    for base in ("C:/Program Files (x86)/Inno Setup 6", "C:/Program Files/Inno Setup 6",
                 str(Path.home() / "AppData/Local/Programs/Inno Setup 6")):
        candidate = Path(base) / "ISCC.exe"
        if candidate.exists():
            return str(candidate)
    return None


def main() -> None:
    from anihub import __version__

    icon = make_icon()
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--name", "AniHUB",
            "--icon", str(icon), "--paths", str(ROOT / "src"), "--distpath", str(ROOT / "dist"),
            "--workpath", str(ROOT / "build" / "pyi"), "--specpath", str(ROOT / "build")]
    args += ["--add-data", f"{ROOT / 'src' / 'anihub' / 'data'};anihub/data"]       # pictures of the prompt builder's tags
    args += ["--collect-submodules", "anihub.core.lang"]        # the translation tables are imported by name at run time
    for mod in EXCLUDES:
        args += ["--exclude-module", mod]
    args.append(str(ROOT / "packaging" / "entry.py"))
    subprocess.run(args, check=True, cwd=ROOT)
    iscc = find_iscc()
    if not iscc:
        sys.exit("Inno Setup (ISCC.exe) not found: install it with `winget install JRSoftware.InnoSetup`")
    subprocess.run([iscc, f"/DAppVersion={__version__}", str(ROOT / "packaging" / "installer.iss")], check=True, cwd=ROOT)
    print("installer:", ROOT / "dist" / f"AniHUB-Setup-{__version__}.exe")


if __name__ == "__main__":
    main()
