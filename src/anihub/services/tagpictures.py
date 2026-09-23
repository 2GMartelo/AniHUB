"""Drawing the picture of a tag with Forge: the tag on the standard character (see promptbook.DEFAULT_CHARACTER). Shared by the prompt
builder ("draw this picture", "draw all of them") and tools/make_tag_pictures.py."""
from __future__ import annotations

import random
import shutil
import tempfile
from pathlib import Path

from anihub.services import generation, promptbook as pb

SEED_MAX = 2**31 - 1   # the usual Stable Diffusion / A1111-API seed range; -1 there means "pick one at random" instead


class PictureMaker:
    """Blocking (call it from a worker thread). `api` is a running ForgeApi, `character` the standard character settings.
    One instance is normally reused for a whole batch (one tag or "redraw all"): `_salt` is picked once per instance, so
    every picture in THAT batch still uses the seed scheme's existing tag-to-tag offsets (comparable side by side, e.g.
    a hair-colour catalogue), but drawing the very same tag again later -- a fresh PictureMaker -- lands on a different
    picture instead of the previous run's identical one."""

    def __init__(self, api, character: dict | None = None, model_override: str = ""):
        self.api = api
        self.character = pb.character_from(character)
        self._needle = (model_override or self.character["model"]).strip()
        self._title: str | None = None
        self._salt = random.SystemRandom().randint(0, SEED_MAX)

    def model_title(self) -> str:
        """The checkpoint title Forge knows for the configured name ("" = keep Forge's current model)."""
        if self._title is None:
            self._title = ""
            if self._needle:
                found = next((m["title"] for m in self.api.models() if self._needle.lower() in m["title"].lower()), "")
                if not found:
                    raise ValueError(f"no checkpoint matches {self._needle!r}")
                self._title = found
        return self._title

    def params_for(self, row: dict, category_key: str = "") -> generation.GenParams:
        ch = self.character
        prompt, negative = pb.preview_prompt(row["slot"], row["text"], category_key, ch)
        seed = (int(ch["seed"]) + self._salt + (row["id"] if row["slot"] in pb.VARIED_SEED_SLOTS else 0)) % SEED_MAX
        return generation.GenParams(prompt=prompt, negative_prompt=negative, model=self.model_title(), steps=int(ch["steps"]),
                                    cfg_scale=float(ch["cfg"]), width=int(ch["size"]), height=int(ch["size"]), seed=seed,
                                    sampler_name=ch["sampler"] or "Euler a")

    def draw(self, row: dict, category_key: str = "") -> bytes:
        """The picture of the tag as image bytes."""
        tmp = Path(tempfile.mkdtemp(prefix="anihub_tag_"))
        try:
            results = generation.run_generation(self.api, self.params_for(row, category_key), tmp)
            return Path(results[0].path).read_bytes()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
