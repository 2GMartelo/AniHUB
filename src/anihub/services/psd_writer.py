"""Building a layered PSD from RGBA picture layers -- the hand-off to Krita/Photoshop/Stretchy Studio/Live2D Cubism
that Stage 3 of ТЗ_rasshirenie_prilozheniya.md ends with. Uses pytoshop (BSD license) rather than hand-rolling the PSD
binary format: layer records, per-channel compression, Unicode layer names and canvas bounds are all finicky enough
that reusing a maintained implementation is worth the extra dependency.

Two things about pytoshop are not obvious from its own docs and were confirmed by writing a file and reading it back
(see tests/test_psd_writer.py):
- `nested_layers_to_psd(layers, ..., size=(width, height))` -- despite its own docstring saying "(height, width)",
  the code unpacks it as (width, height). Passing the two swapped silently mislabels the file's own dimensions.
- Layer order in the list is Photoshop's own layer-panel order: index 0 is the TOPMOST (frontmost) layer, matching
  how Photoshop displays its own layer list -- not file storage order (pytoshop reverses the list for that itself).

pytoshop's compiled RLE codec (a Cython extension) is not guaranteed to be built on a plain `pip install` -- it needs
a C compiler that most of this app's users will not have. write_psd always asks for zip (zlib, stdlib-only)
compression instead: always available, and it compresses these mostly-transparent character-part layers well."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class PsdLayer:
    """One layer to place in the PSD. `image` is an RGBA numpy array (H, W, 4), uint8, straight (non-premultiplied)
    alpha. `x`/`y` are its top-left corner on the canvas."""
    name: str
    image: np.ndarray
    x: int = 0
    y: int = 0


def write_psd(path: Path, layers: list[PsdLayer], width: int, height: int) -> None:
    """Write `layers` (index 0 = topmost -- see PsdLayer) as one layered RGBA PSD at `path`, canvas `width` x
    `height`. Raises ValueError if `layers` is empty (pytoshop itself refuses a PSD with no images) or a layer's
    `image` is not an (H, W, 4) array."""
    if not layers:
        raise ValueError("write_psd needs at least one layer")
    from pytoshop import enums
    from pytoshop.user import nested_layers

    images = []
    for layer in layers:
        img = np.ascontiguousarray(layer.image)
        if img.ndim != 3 or img.shape[2] != 4:
            raise ValueError(f"layer {layer.name!r}: expected an (H, W, 4) RGBA array, got {img.shape}")
        h, w = img.shape[:2]
        channels = {0: img[..., 0], 1: img[..., 1], 2: img[..., 2], -1: img[..., 3]}
        images.append(nested_layers.Image(
            name=layer.name, top=int(layer.y), left=int(layer.x), bottom=int(layer.y) + h, right=int(layer.x) + w,
            channels=channels, color_mode=enums.ColorMode.rgb))

    psd = nested_layers.nested_layers_to_psd(images, enums.ColorMode.rgb, size=(int(width), int(height)),
                                             compression=enums.Compression.zip)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        psd.write(fh)
