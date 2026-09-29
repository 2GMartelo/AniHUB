"""Cross-section bridges: a library picture becoming an SD img2img source or a VTube input. Kept out of
main_window.py itself, which otherwise ends up owning logic that belongs to neither section any more than it
belongs to MainWindow -- it is just the thing both signals happen to be wired through."""
from __future__ import annotations

from pathlib import Path

from anihub.ui.library_view import row_prompt


def to_img2img(win, row: dict) -> None:
    """Open the SD section with the chosen library picture as the img2img source."""
    path = win.ctx.paths.root / (row["trash_path"] if row.get("trashed_at") and row.get("trash_path") else row["path"])
    prompt, negative = row_prompt(win.ctx, row)
    win.go("sd")
    win.sd_page.show_generate_tab()
    win.sd_page.generate.use_as_init(Path(path), prompt, negative)


def to_vtube(win, path: Path) -> None:
    """Open the SD section with the chosen library picture loaded into the VTube tab's own picture picker."""
    win.go("sd")
    if win.sd_page.vtube is not None:
        win.sd_page.tabs.setCurrentWidget(win.sd_page.vtube)
        win.sd_page.vtube.load_path(path)
