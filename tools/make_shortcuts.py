r"""Creates Desktop shortcuts for AniHUB (and its "AniHUB Music" launcher, opened straight on Anime > Music).

    .venv\Scripts\python tools\make_shortcuts.py [--music] [--no-icon]

By default points at run.bat / run_music.bat (the hidden-console dev launcher: always runs the current source through .venv).
Pass --use-build to point at dist\AniHUB\AniHUB.exe / "AniHUB Music.exe" instead -- only do that right after packaging\build.py,
since a shortcut to an old dist build would silently run yesterday's code.
No extra Python package needed: the .lnk files are made through PowerShell's WScript.Shell COM object.
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PS_TEMPLATE = """
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut([System.IO.Path]::Combine([Environment]::GetFolderPath('Desktop'), {name!r} + '.lnk'))
$link.TargetPath = {target!r}
$link.Arguments = {args!r}
$link.WorkingDirectory = {workdir!r}
{icon_line}
$link.Save()
"""


def make_shortcut(name: str, target: Path, args: str, icon: Path | None) -> None:
    icon_line = f"$link.IconLocation = '{icon}'" if icon else ""
    script = PS_TEMPLATE.format(name=name, target=str(target), args=args, workdir=str(target.parent), icon_line=icon_line)
    subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script], check=True, cwd=ROOT)
    print(f"desktop shortcut: {name}.lnk -> {target} {args}".rstrip())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--music", action="store_true", help="also add the Music shortcut")
    ap.add_argument("--use-build", action="store_true", help="point at the packaged dist\\AniHUB build instead of the dev launcher")
    ap.add_argument("--no-icon", action="store_true")
    args = ap.parse_args()

    built = ROOT / "dist" / "AniHUB"
    icon = None if args.no_icon else (ROOT / "build" / "anihub.ico" if (ROOT / "build" / "anihub.ico").is_file() else None)

    if args.use_build and (built / "AniHUB.exe").is_file():
        make_shortcut("AniHUB", built / "AniHUB.exe", "", icon)
    else:
        make_shortcut("AniHUB", ROOT / "run.bat", "", icon)

    if args.music:
        if args.use_build and (built / "AniHUB Music.exe").is_file():
            make_shortcut("AniHUB Music", built / "AniHUB Music.exe", "", icon)
        else:
            make_shortcut("AniHUB Music", ROOT / "run_music.bat", "", icon)


if __name__ == "__main__":
    if sys.platform != "win32":
        sys.exit("Windows only (uses PowerShell's WScript.Shell)")
    main()
