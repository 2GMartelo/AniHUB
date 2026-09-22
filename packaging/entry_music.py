"""PyInstaller entry point for the "AniHUB Music" launcher: a separate, tiny .exe that starts the very same program straight on
Anime > Music, for people who mainly want the radio/music player and would rather not click through to it every time.

It does not duplicate the (large) main PySide6 bundle: packaging/build.py builds it from the main AniHUB folder, so both
executables share one install of the app and its libraries."""
import sys

from anihub.app import main

if __name__ == "__main__":
    sys.argv.append("--music")
    sys.exit(main())
